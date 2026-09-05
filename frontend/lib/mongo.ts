// mongo.ts — one MongoClient for the whole process.
//
// Next.js route handlers run per request. Constructing a MongoClient inside
// one exhausts the Atlas connection pool within minutes, and an M0 cluster has
// a small cap — this is the single most expensive mistake available in this
// file, and it is why the client is cached at module scope
// (WORK_DISTRIBUTION §5.2, IMPLEMENTATION_PLAN §6.14).
//
// In development Next reloads modules on edit, which would leak a client per
// reload, so the cache is parked on globalThis where the reload cannot see it.

import { MongoClient, type Collection, type Db, type Document } from 'mongodb';

export const isMongoConfigured = Boolean(process.env.MONGODB_URI);

/** Thrown when a route needs the database and there isn't one. Becomes a 503. */
export class MongoNotConfiguredError extends Error {
  readonly status = 503;
  constructor() {
    super(
      'MONGODB_URI is not set — persistence is unavailable. See .env.local.example.'
    );
    this.name = 'MongoNotConfiguredError';
  }
}

const globalCache = globalThis as unknown as {
  _avr25dMongo?: Promise<MongoClient>;
};

function client(): Promise<MongoClient> {
  const uri = process.env.MONGODB_URI;
  if (!uri) throw new MongoNotConfiguredError();
  if (!globalCache._avr25dMongo) {
    globalCache._avr25dMongo = new MongoClient(uri, {
      // An M0 cluster is small; a handful of sockets is plenty for a demo and
      // leaves headroom for the bench harness connecting at the same time.
      maxPoolSize: 10,
      serverSelectionTimeoutMS: 5000,
    }).connect();
  }
  return globalCache._avr25dMongo;
}

export async function db(): Promise<Db> {
  return (await client()).db(process.env.MONGODB_DB ?? 'avr25d');
}

// ── Documents (IMPLEMENTATION_PLAN §6.14) ─────────────────────────────────

/** FR-38 — one per pipeline or benchmark run, carrying the numbers' provenance. */
export interface RunDoc extends Document {
  uid: string;
  startedAt: Date;
  finishedAt?: Date;
  gitCommit?: string;
  platform?: string;
  mode?: string;
  /** Snapshot of config.yaml as it was for this run. */
  config?: unknown;
  /** The results.json payload. */
  results?: unknown;
}

/** FR-39 — the routing audit trail. */
export interface DecisionDoc extends Document {
  runId: string;
  uid: string;
  frameId: number;
  tSec: number;
  selected: string;
  risk: string;
  etaS: number;
  reason: string;
  trackIds: number[];
  /** True when this record was triggered by a change rather than the heartbeat. */
  changed: boolean;
}

/** FR-40 — scene ground truth, read from the same store the dashboard reads. */
export interface SceneDoc extends Document {
  name: string;
  primitives?: unknown;
  groundTruth?: Record<string, number>;
}

export interface UserDoc extends Document {
  _id: string; // the Firebase uid
  email?: string;
  displayName?: string;
  createdAt: Date;
}

export async function runs(): Promise<Collection<RunDoc>> {
  return (await db()).collection<RunDoc>('runs');
}
export async function decisions(): Promise<Collection<DecisionDoc>> {
  return (await db()).collection<DecisionDoc>('decisions');
}
export async function scenes(): Promise<Collection<SceneDoc>> {
  return (await db()).collection<SceneDoc>('scenes');
}
export async function users(): Promise<Collection<UserDoc>> {
  return (await db()).collection<UserDoc>('users');
}

/**
 * Create the indexes from §6.14. Safe to call repeatedly — createIndex is
 * idempotent — so routes can call it lazily rather than needing a setup step
 * somebody has to remember to run.
 */
let indexesReady: Promise<void> | null = null;
export function ensureIndexes(): Promise<void> {
  if (!indexesReady) {
    indexesReady = (async () => {
      const [r, d, s] = await Promise.all([runs(), decisions(), scenes()]);
      await Promise.all([
        r.createIndex({ uid: 1, startedAt: -1 }),
        d.createIndex({ runId: 1, frameId: 1 }),
        s.createIndex({ name: 1 }, { unique: true }),
      ]);
    })().catch((err) => {
      // Don't cache a failure: the next request should retry rather than be
      // told forever that indexing failed once at startup.
      indexesReady = null;
      throw err;
    });
  }
  return indexesReady;
}

/** Map a configuration failure to 503; anything else is the caller's problem. */
export function serviceUnavailableResponse(err: unknown): Response {
  if (err instanceof MongoNotConfiguredError) {
    return Response.json({ error: err.message }, { status: 503 });
  }
  throw err;
}
