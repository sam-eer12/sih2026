// api.ts — shared error mapping for route handlers.
//
// Only the *error* path is shared. requireUser() is called explicitly at the
// top of every handler rather than wrapped in a withAuth() helper, because
// T-W2 asserts the guard per route and a wrapper is exactly how one handler
// ends up quietly unwrapped.

import { UnauthorizedError } from './firebase/admin';
import { MongoNotConfiguredError } from './mongo';

/** 400 for a request this server will never accept as written. */
export class BadRequestError extends Error {
  readonly status = 400;
  constructor(message: string) {
    super(message);
    this.name = 'BadRequestError';
  }
}

/**
 * Turn a thrown error into a Response.
 *
 * Unexpected errors become a bare 500: the message could name a collection, a
 * connection string or a driver internal, and none of that belongs in a
 * response body. It goes to the server log instead.
 */
export function handleRouteError(err: unknown): Response {
  if (err instanceof UnauthorizedError) {
    return Response.json({ error: err.message }, { status: 401 });
  }
  if (err instanceof BadRequestError) {
    return Response.json({ error: err.message }, { status: 400 });
  }
  if (err instanceof MongoNotConfiguredError) {
    return Response.json({ error: err.message }, { status: 503 });
  }
  console.error('[api] unhandled error:', err);
  return Response.json({ error: 'Internal error' }, { status: 500 });
}

/** Parse a JSON body, or fail as 400 rather than 500. */
export async function readJson<T>(req: Request): Promise<T> {
  try {
    return (await req.json()) as T;
  } catch {
    throw new BadRequestError('Body must be valid JSON');
  }
}
