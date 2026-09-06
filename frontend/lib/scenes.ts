// scenes.ts — accepting Sameer's FR-40 scene registry.
//
// `avr25d.synth.registry` derives ground truth from the scene CSVs alone and
// writes model/data/scenes_registry.json:
//
//   { schemaVersion, collection: "scenes", generator, scenes: [ … ] }
//
// Each element is already a MongoDB `scenes` document — `_id` is the scene
// name, and alongside `groundTruth` it carries `hazards`, `sensor`,
// `nPrimitives`, `expectNoHazards` and a `source` block with the CSV's
// sha256.
//
// The first version of the API route accepted only `{name, primitives,
// groundTruth}` and would have silently dropped the rest — including the
// sha256, which is the whole reason T-W5 can claim the stored truth matches
// the CSV. So documents are stored **whole**: this file validates the shape
// and normalises the key, and changes nothing else. If Sameer adds a field it
// arrives without a frontend change.

/** What the registry writes, and what a caller may POST. */
export interface SceneDocument {
  name: string;
  groundTruth?: Record<string, number | null>;
  [key: string]: unknown;
}

export class SceneValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SceneValidationError';
  }
}

/** Registry files above this are refused rather than half-understood. */
export const SUPPORTED_SCHEMA_VERSION = 1;

/** Guards a single request; the registry is 7 scenes today. */
export const MAX_SCENES_PER_REQUEST = 200;

/**
 * Accept one document, an array, or a whole registry file.
 *
 * Taking the registry's own shape means seeding is `POST` the file, with no
 * reshaping step in between to drift out of sync with the generator.
 */
export function parseScenePayload(body: unknown): SceneDocument[] {
  if (typeof body !== 'object' || body === null) {
    throw new SceneValidationError('Body must be an object or an array of scenes');
  }

  let raw: unknown[];
  if (Array.isArray(body)) {
    raw = body;
  } else if (Array.isArray((body as { scenes?: unknown }).scenes)) {
    const registry = body as { scenes: unknown[]; schemaVersion?: unknown };
    if (
      typeof registry.schemaVersion === 'number' &&
      registry.schemaVersion > SUPPORTED_SCHEMA_VERSION
    ) {
      throw new SceneValidationError(
        `Registry schemaVersion ${registry.schemaVersion} is newer than this app ` +
          `understands (${SUPPORTED_SCHEMA_VERSION}). Update the frontend rather ` +
          `than storing a document it cannot read.`
      );
    }
    raw = registry.scenes;
  } else {
    raw = [body];
  }

  if (raw.length === 0) throw new SceneValidationError('No scenes in the payload');
  if (raw.length > MAX_SCENES_PER_REQUEST) {
    throw new SceneValidationError(`At most ${MAX_SCENES_PER_REQUEST} scenes per request`);
  }
  return raw.map(validateScene);
}

function validateScene(raw: unknown, index: number): SceneDocument {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    throw new SceneValidationError(`scenes[${index}] is not an object`);
  }
  const doc = raw as Record<string, unknown>;
  const name = doc.name ?? doc._id;
  if (typeof name !== 'string' || name.length === 0) {
    throw new SceneValidationError(`scenes[${index}] needs a string \`name\``);
  }
  if (
    doc.groundTruth !== undefined &&
    (typeof doc.groundTruth !== 'object' || doc.groundTruth === null)
  ) {
    throw new SceneValidationError(`scenes[${index}].groundTruth must be an object`);
  }
  return { ...doc, name } as SceneDocument;
}

/**
 * Split a document into its Mongo `_id` and the fields to `$set`.
 *
 * `_id` is immutable, so it must be the filter and never part of the update —
 * Mongo rejects an update that touches it. The registry already uses the
 * scene name as `_id`, so this preserves its idempotency: re-seeding updates
 * in place instead of duplicating the collection.
 */
export function toSceneUpdate(doc: SceneDocument): {
  id: string;
  fields: Record<string, unknown>;
} {
  const { _id, ...fields } = doc as Record<string, unknown> & { _id?: unknown };
  void _id;
  return { id: doc.name, fields };
}
