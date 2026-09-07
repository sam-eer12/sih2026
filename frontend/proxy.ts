// proxy.ts — the route gate (FR-36, T-W1).
//
// This is `proxy.ts`, not `middleware.ts`: Next.js 16 renamed the convention
// and deprecated the old filename. Same functionality, different file and
// export name (node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md).
//
// ── This is an optimistic check, and that is on purpose ───────────────────
// The Next docs are explicit that proxy runs on every route including
// prefetches, so it must only read the cookie and never hit a database or
// verify a token. It exists to redirect signed-out users to the login page —
// a UX concern. It is NOT the security boundary.
//
// The security boundary is requireUser() in lib/firebase/admin.ts, which
// verifies the ID token with the Admin SDK inside every route handler that
// writes (FR-37, T-W2). Anyone can forge the marker cookie; all that buys them
// is the ability to load a dashboard whose API calls will 401.
//
// ── Why auth is skipped when unconfigured ─────────────────────────────────
// The Firebase project is an external dependency that does not exist yet, and
// the live demo runs from this app. Gating the dashboard on a project nobody
// has created would take the demo offline to enforce a login page that cannot
// work. So when the config is absent the gate is inert and the app behaves
// exactly as it did before auth existed. Setting the NEXT_PUBLIC_FIREBASE_*
// values turns it on with no other change.

import { NextResponse, type NextRequest } from 'next/server';
import { AUTH_COOKIE } from './lib/authCookie';

/** Routes that require a session. Everything else is public. */
const PROTECTED = ['/dashboard', '/runs'];

/**
 * Auth is live only when the client SDK has something to talk to. Read at
 * module scope: NEXT_PUBLIC_* values are inlined at build time.
 */
const AUTH_ENABLED = Boolean(
  process.env.NEXT_PUBLIC_FIREBASE_API_KEY &&
    process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN &&
    process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID
);

export function proxy(request: NextRequest) {
  if (!AUTH_ENABLED) return NextResponse.next();

  const { pathname, search } = request.nextUrl;
  const isProtected = PROTECTED.some(
    (base) => pathname === base || pathname.startsWith(`${base}/`)
  );
  const signedIn = request.cookies.get(AUTH_COOKIE)?.value === '1';

  if (isProtected && !signedIn) {
    const login = new URL('/login', request.url);
    // Come back to where they were aiming once they are through.
    login.searchParams.set('next', `${pathname}${search}`);
    return NextResponse.redirect(login);
  }

  // A signed-in user has no reason to look at the login page.
  if (pathname === '/login' && signedIn) {
    return NextResponse.redirect(new URL('/dashboard', request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/dashboard/:path*', '/runs/:path*', '/login'],
};
