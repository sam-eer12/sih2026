// admin.ts — server-side token verification (FR-37).
//
// Every route handler that writes calls requireUser() FIRST, before it touches
// MongoDB. T-W2 asserts that per route rather than once globally, because a
// single unprotected handler is the whole vulnerability — and "we verify in a
// helper somewhere" is exactly how one gets missed.
//
// No handler ever trusts a client-supplied uid. The uid comes from the decoded
// token or the request is rejected.

import { cert, getApps, getApp, initializeApp, type App } from 'firebase-admin/app';
import { getAuth, type DecodedIdToken } from 'firebase-admin/auth';

/** Thrown for anything that should become a 401. Carries no detail a caller could probe. */
export class UnauthorizedError extends Error {
  readonly status = 401;
  constructor(message = 'Unauthorized') {
    super(message);
    this.name = 'UnauthorizedError';
  }
}

/**
 * The service account, as a single-line JSON string in FIREBASE_SERVICE_ACCOUNT.
 *
 * IMPLEMENTATION_PLAN §2.3: it is never committed. If it is ever pasted into
 * the repo by accident, rotate it and tell the team — a leaked service account
 * is full admin access to the project, not just read access.
 */
function serviceAccount(): Record<string, string> | null {
  const raw = process.env.FIREBASE_SERVICE_ACCOUNT;
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    // A malformed key is a deployment mistake, not a client error. Say so
    // loudly at the server rather than letting every request 401 mysteriously.
    throw new Error(
      'FIREBASE_SERVICE_ACCOUNT is set but is not valid JSON — it must be the ' +
        'service-account file collapsed onto one line.'
    );
  }
}

export const isAdminConfigured = Boolean(process.env.FIREBASE_SERVICE_ACCOUNT);

function adminApp(): App {
  if (getApps().length) return getApp();
  const creds = serviceAccount();
  if (!creds) {
    throw new Error(
      'FIREBASE_SERVICE_ACCOUNT is not set — server-side token verification is ' +
        'unavailable. See .env.local.example.'
    );
  }
  return initializeApp({ credential: cert(creds) });
}

/**
 * Pull the bearer token out of an Authorization header.
 *
 * Split out from requireUser so the reject-before-any-database-work path is
 * testable without a Firebase project: everything malformed is caught here,
 * synchronously, before adminApp() is ever constructed.
 */
export function extractBearerToken(req: Request): string | null {
  const header = req.headers.get('authorization') ?? req.headers.get('Authorization');
  if (!header) return null;
  const match = /^Bearer\s+(.+)$/i.exec(header.trim());
  if (!match) return null;
  const token = match[1].trim();
  return token.length > 0 ? token : null;
}

/**
 * Verify the caller's Firebase ID token. Throws UnauthorizedError otherwise.
 *
 * Call this before any Mongo access, not after and not alongside.
 */
export async function requireUser(req: Request): Promise<DecodedIdToken> {
  const token = extractBearerToken(req);
  if (!token) throw new UnauthorizedError('Missing bearer token');

  try {
    // checkRevoked: a signed-out or disabled user should stop working
    // immediately, not in up to an hour when the token would have expired.
    return await getAuth(adminApp()).verifyIdToken(token, true);
  } catch (cause) {
    if (cause instanceof Error && /FIREBASE_SERVICE_ACCOUNT/.test(cause.message)) {
      throw cause; // configuration problem — do not disguise it as a 401
    }
    throw new UnauthorizedError('Invalid or expired token');
  }
}

/** Turn an UnauthorizedError into a Response; rethrow anything else. */
export function unauthorizedResponse(err: unknown): Response {
  if (err instanceof UnauthorizedError) {
    return Response.json({ error: err.message }, { status: 401 });
  }
  throw err;
}
