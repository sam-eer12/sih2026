// api/scenes — FR-40. Scene ground truth, in the store the dashboard reads.
//
// The point of this collection is that the hazard comparison reads truth from
// the same place the dashboard reads everything else, rather than from a
// constant someone typed into a slide. Registration is an upsert keyed on
// name, so re-running it is idempotent.
//
// Populating it is not this route's job. The ground-truth values belong to the
// synthetic scenes in avr25d/synth/scenes/*.csv, which are Sameer's, and
// deriving pothole depth or gantry clearance from a primitive list is domain
// work that should live with the scenes rather than be re-implemented here.
// This endpoint accepts what that produces (T-W5 then checks the two agree).

import { requireUser } from '../../../lib/firebase/admin';
import { ensureIndexes, scenes, type SceneDoc } from '../../../lib/mongo';
import { BadRequestError, handleRouteError, readJson } from '../../../lib/api';

export const dynamic = 'force-dynamic';

interface SceneBody {
  name?: string;
  primitives?: unknown;
  groundTruth?: Record<string, number>;
}

export async function POST(req: Request): Promise<Response> {
  try {
    await requireUser(req);                        // FR-37 — before any Mongo call
    const body = await readJson<SceneBody>(req);

    if (!body.name || typeof body.name !== 'string') {
      throw new BadRequestError('`name` is required');
    }
    if (body.groundTruth !== undefined && typeof body.groundTruth !== 'object') {
      throw new BadRequestError('`groundTruth` must be an object of numbers');
    }

    const doc: SceneDoc = {
      name: body.name,
      primitives: body.primitives,
      groundTruth: body.groundTruth,
    };

    await ensureIndexes();
    // Upsert on the unique name index: registering the same scene twice
    // updates it rather than failing or duplicating.
    await (await scenes()).updateOne(
      { name: body.name },
      { $set: doc },
      { upsert: true }
    );
    return Response.json({ name: body.name }, { status: 201 });
  } catch (err) {
    return handleRouteError(err);
  }
}

export async function GET(req: Request): Promise<Response> {
  try {
    await requireUser(req);
    const name = new URL(req.url).searchParams.get('name');

    await ensureIndexes();
    const col = await scenes();
    const docs = await (name ? col.find({ name }) : col.find({}).sort({ name: 1 })).toArray();

    return Response.json({
      scenes: docs.map((d) => ({ ...d, _id: d._id?.toString() })),
    });
  } catch (err) {
    return handleRouteError(err);
  }
}
