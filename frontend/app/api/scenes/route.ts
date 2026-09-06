// api/scenes — FR-40. Scene ground truth, in the store the dashboard reads.
//
// The point of this collection is that the hazard comparison reads truth from
// the same place the dashboard reads everything else, rather than from a
// constant someone typed into a slide.
//
// Documents are stored **whole**. `avr25d.synth.registry` derives them from
// the scene CSVs and they carry more than a `groundTruth` block: `hazards`,
// `sensor`, `expectNoHazards`, and a `source` with the CSV's sha256 — which is
// what lets T-W5 claim the stored truth matches the CSV rather than merely
// resembling it. An earlier version of this route accepted only
// `{name, primitives, groundTruth}` and would have dropped all of that.
//
// Seeding is therefore one POST of model/data/scenes_registry.json:
//
//   make scenes-registry
//   curl -X POST localhost:3000/api/scenes -H "Authorization: Bearer $TOKEN" \
//        -H 'Content-Type: application/json' \
//        --data @model/data/scenes_registry.json

import { requireUser } from '../../../lib/firebase/admin';
import { ensureIndexes, scenes } from '../../../lib/mongo';
import { BadRequestError, handleRouteError, readJson } from '../../../lib/api';
import {
  parseScenePayload,
  toSceneUpdate,
  SceneValidationError,
} from '../../../lib/scenes';

export const dynamic = 'force-dynamic';

export async function POST(req: Request): Promise<Response> {
  try {
    await requireUser(req);                        // FR-37 — before any Mongo call
    const body = await readJson<unknown>(req);

    let documents;
    try {
      documents = parseScenePayload(body);
    } catch (err) {
      // A malformed registry is the caller's mistake, not a server fault.
      if (err instanceof SceneValidationError) throw new BadRequestError(err.message);
      throw err;
    }

    await ensureIndexes();
    const col = await scenes();

    // Upsert on the scene name, which is also the registry's own `_id`, so
    // re-seeding updates in place rather than duplicating the collection.
    const results = await Promise.all(
      documents.map(async (doc) => {
        const { id, fields } = toSceneUpdate(doc);
        await col.updateOne({ _id: id }, { $set: fields }, { upsert: true });
        return id;
      })
    );

    return Response.json({ scenes: results, count: results.length }, { status: 201 });
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

    return Response.json({ scenes: docs });
  } catch (err) {
    return handleRouteError(err);
  }
}
