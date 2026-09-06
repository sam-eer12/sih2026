// api/runs — FR-38. Where a number in the deck traces back to.
//
// Every figure on a slide comes from a results.json, and every results.json
// lands here with the config and git commit that produced it. When a judge
// asks "where did 22.67x come from", the answer is a run id rather than a
// memory.
//
// T-W2: requireUser() is the first statement in both handlers, before any
// Mongo call. T-W3: config and results are stored exactly as received and
// returned exactly as stored, so a round-trip is byte-identical.

import { ObjectId } from 'mongodb';
import { requireUser } from '../../../lib/firebase/admin';
import { ensureIndexes, runs, type RunDoc } from '../../../lib/mongo';
import { BadRequestError, handleRouteError, readJson } from '../../../lib/api';

/** Persistence is per-user and per-request; nothing here may be cached. */
export const dynamic = 'force-dynamic';

interface RunBody {
  startedAt?: string;
  finishedAt?: string;
  gitCommit?: string;
  platform?: string;
  mode?: string;
  config?: unknown;
  results?: unknown;
}

export async function POST(req: Request): Promise<Response> {
  try {
    const user = await requireUser(req);          // FR-37 — before any Mongo call
    const body = await readJson<RunBody>(req);

    if (body.results === undefined && body.config === undefined) {
      throw new BadRequestError('A run needs at least one of `config` or `results`');
    }

    const doc: RunDoc = {
      // The uid comes from the verified token, never from the body. A client
      // that sends one is ignored rather than trusted.
      uid: user.uid,
      startedAt: parseDate(body.startedAt) ?? new Date(),
      finishedAt: parseDate(body.finishedAt),
      gitCommit: body.gitCommit,
      platform: body.platform,
      mode: body.mode,
      config: body.config,
      results: body.results,
    };

    await ensureIndexes();
    const { insertedId } = await (await runs()).insertOne(doc);
    return Response.json({ id: insertedId.toString() }, { status: 201 });
  } catch (err) {
    return handleRouteError(err);
  }
}

export async function GET(req: Request): Promise<Response> {
  try {
    const user = await requireUser(req);          // read path is scoped to the caller too
    const params = new URL(req.url).searchParams;
    const id = params.get('id');

    // Single run, for the detail page. Always filtered by uid as well as _id,
    // so a guessed id from another account returns nothing rather than
    // somebody else's results.
    if (id) {
      if (!ObjectId.isValid(id)) throw new BadRequestError(`Not a run id: ${id}`);
      await ensureIndexes();
      const doc = await (await runs()).findOne({ _id: new ObjectId(id), uid: user.uid });
      if (!doc) return Response.json({ error: 'Run not found' }, { status: 404 });
      return Response.json({ run: { ...doc, _id: doc._id?.toString() } });
    }

    const limit = clampLimit(params.get('limit'));

    await ensureIndexes();
    const docs = await (await runs())
      .find({ uid: user.uid })                     // uses {uid:1, startedAt:-1}
      .sort({ startedAt: -1 })
      .limit(limit)
      .toArray();

    return Response.json({
      runs: docs.map((d) => ({ ...d, _id: d._id?.toString() })),
    });
  } catch (err) {
    return handleRouteError(err);
  }
}

/**
 * Close a run — set `finishedAt` when the dashboard session ends.
 *
 * Scoped by uid as well as _id, so this cannot touch another account's run
 * even with a valid token and a guessed id. Only `finishedAt` is writable:
 * the config and results are the provenance of every number in the deck and
 * must not be editable after the fact.
 */
export async function PATCH(req: Request): Promise<Response> {
  try {
    const user = await requireUser(req);          // FR-37 — before any Mongo call
    const body = await readJson<{ id?: string; finishedAt?: string }>(req);

    if (!body.id || !ObjectId.isValid(body.id)) {
      throw new BadRequestError('`id` must be a run id');
    }
    const finishedAt = parseDate(body.finishedAt) ?? new Date();

    await ensureIndexes();
    const result = await (await runs()).updateOne(
      { _id: new ObjectId(body.id), uid: user.uid },
      { $set: { finishedAt } }
    );
    if (result.matchedCount === 0) {
      return Response.json({ error: 'Run not found' }, { status: 404 });
    }
    return Response.json({ id: body.id, finishedAt: finishedAt.toISOString() });
  } catch (err) {
    return handleRouteError(err);
  }
}

function parseDate(value: string | undefined): Date | undefined {
  if (!value) return undefined;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) throw new BadRequestError(`Not a date: ${value}`);
  return d;
}

/** Bounded so a stray ?limit=1000000 cannot ask Atlas for the whole collection. */
function clampLimit(raw: string | null): number {
  const n = Number(raw ?? 50);
  if (!Number.isFinite(n) || n <= 0) return 50;
  return Math.min(Math.floor(n), 200);
}
