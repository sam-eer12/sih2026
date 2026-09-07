// api/users — the `users` collection from IMPLEMENTATION_PLAN §6.14.
//
// A profile row keyed on the Firebase uid, so a run can be attributed to a
// person rather than an opaque identifier when the history is read back.
//
// Everything here comes from the verified token — email and display name
// included. Taking them from the body would let any signed-in caller write
// somebody else's name into the record, and the token already carries both.

import { requireUser } from '../../../lib/firebase/admin';
import { ensureIndexes, users, type UserDoc } from '../../../lib/mongo';
import { handleRouteError } from '../../../lib/api';

export const dynamic = 'force-dynamic';

/** Idempotent: called on every sign-in, inserts once and refreshes after that. */
export async function POST(req: Request): Promise<Response> {
  try {
    const user = await requireUser(req);          // FR-37 — before any Mongo call

    const profile: Partial<UserDoc> = {
      email: user.email,
      displayName: (user.name as string | undefined) ?? undefined,
    };

    await ensureIndexes();
    await (await users()).updateOne(
      { _id: user.uid },                          // _id IS the uid; no extra index needed
      {
        $set: profile,
        $setOnInsert: { createdAt: new Date() },   // first sight, not last
      },
      { upsert: true }
    );

    return Response.json({ uid: user.uid }, { status: 201 });
  } catch (err) {
    return handleRouteError(err);
  }
}

export async function GET(req: Request): Promise<Response> {
  try {
    const user = await requireUser(req);
    await ensureIndexes();
    const doc = await (await users()).findOne({ _id: user.uid });
    return Response.json({ user: doc ?? null });
  } catch (err) {
    return handleRouteError(err);
  }
}
