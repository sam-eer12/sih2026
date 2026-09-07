// authCookie.ts — the one fact the proxy and the client both need.
//
// Kept in its own module with no imports because `proxy.ts` runs in the edge
// runtime and must not pull in the Firebase client SDK to learn a string.

/**
 * Presence marker for the optimistic route gate. It carries "1" and nothing
 * else — never a token.
 *
 * Firebase keeps its ID tokens in IndexedDB, which the proxy cannot read, so
 * something has to be in a cookie for a route gate to work at all. Putting the
 * ID token there would expose it to any XSS on the page for no benefit: the
 * proxy only needs to know whether to redirect, and every request that
 * actually touches data re-proves identity server-side with the Admin SDK
 * (FR-37). So the cookie is a hint for UX, not a credential, and it is
 * readable by design.
 */
export const AUTH_COOKIE = 'avr25d_auth';

/** Roughly a Firebase ID token's lifetime; refreshed on every token change. */
export const AUTH_COOKIE_MAX_AGE_S = 60 * 60;
