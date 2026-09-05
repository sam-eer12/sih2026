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
    const limit = clampLimit(new URL(req.url).searchParams.get('limit'));

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
