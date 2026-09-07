// api/decisions — FR-39. The routing audit trail, written in batches.
//
// At 30 FPS a record per frame is 30 Atlas round-trips a second storing
// thirty near-identical documents. The batching that prevents that lives on
// the client in lib/decisionLog.ts, where the frame data already is; this
// handler's job is to accept an array and write it in one insertMany.
//
// It still validates every element, because "the client batches correctly" is
// not something a write endpoint should assume.

import { requireUser } from '../../../lib/firebase/admin';
import { decisions, ensureIndexes, type DecisionDoc } from '../../../lib/mongo';
import { BadRequestError, handleRouteError, readJson } from '../../../lib/api';

export const dynamic = 'force-dynamic';

/** One flush of a 2 s timer at 30 FPS cannot legitimately be larger than this. */
const MAX_BATCH = 500;

interface DecisionBody {
  runId?: string;
  records?: unknown[];
}

export async function POST(req: Request): Promise<Response> {
  try {
    const user = await requireUser(req);          // FR-37 — before any Mongo call
    const body = await readJson<DecisionBody>(req);

    if (!body.runId || typeof body.runId !== 'string') {
      throw new BadRequestError('`runId` is required');
    }
    if (!Array.isArray(body.records)) {
      throw new BadRequestError('`records` must be an array');
    }
    if (body.records.length === 0) {
      return Response.json({ inserted: 0 });
    }
    if (body.records.length > MAX_BATCH) {
      throw new BadRequestError(`At most ${MAX_BATCH} records per request`);
    }

    const docs = body.records.map((r, i) => toDoc(r, body.runId!, user.uid, i));

    await ensureIndexes();
    const result = await (await decisions()).insertMany(docs, { ordered: false });
    return Response.json({ inserted: result.insertedCount }, { status: 201 });
  } catch (err) {
    return handleRouteError(err);
  }
}

export async function GET(req: Request): Promise<Response> {
  try {
    const user = await requireUser(req);
    const runId = new URL(req.url).searchParams.get('runId');
    if (!runId) throw new BadRequestError('`runId` is required');

    await ensureIndexes();
    const docs = await (await decisions())
      .find({ runId, uid: user.uid })              // uses {runId:1, frameId:1}
      .sort({ frameId: 1 })
      .limit(1000)
      .toArray();

    return Response.json({
      decisions: docs.map((d) => ({ ...d, _id: d._id?.toString() })),
    });
  } catch (err) {
    return handleRouteError(err);
  }
}

function toDoc(raw: unknown, runId: string, uid: string, index: number): DecisionDoc {
  if (typeof raw !== 'object' || raw === null) {
    throw new BadRequestError(`records[${index}] is not an object`);
  }
  const r = raw as Record<string, unknown>;
  const frameId = r.frameId;
  if (typeof frameId !== 'number' || !Number.isFinite(frameId)) {
    throw new BadRequestError(`records[${index}].frameId must be a number`);
  }
  return {
    runId,
    uid,                                           // from the token, not the body
    frameId,
    tSec: numberOr(r.tSec, 0),
    selected: stringOr(r.selected, ''),
    risk: stringOr(r.risk, ''),
    etaS: numberOr(r.etaS, 0),
    reason: stringOr(r.reason, ''),
    trackIds: Array.isArray(r.trackIds)
      ? r.trackIds.filter((v): v is number => typeof v === 'number')
      : [],
    changed: r.changed === true,
  };
}

const numberOr = (v: unknown, fallback: number) =>
  typeof v === 'number' && Number.isFinite(v) ? v : fallback;
const stringOr = (v: unknown, fallback: string) =>
  typeof v === 'string' ? v : fallback;
