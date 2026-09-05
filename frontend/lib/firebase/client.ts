// client.ts — Firebase Auth in the browser (FR-36).
//
// Email/password and Google, per the requirement. Everything is lazy: the SDK
// is only initialised when it is actually used, so a build or a page render
// with no Firebase project configured does not throw.
//
// That last point is deliberate. The accounts are external dependencies that
// do not exist yet, and the live demo runs from this app. An import-time
// `initializeApp(undefined)` would take the dashboard down with it, so auth is
// additive: when it is unconfigured the app runs exactly as it did before.
'use client';

import { initializeApp, getApps, getApp, type FirebaseApp } from 'firebase/app';
import {
  getAuth,
  GoogleAuthProvider,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signInWithPopup,
  signOut as fbSignOut,
  onIdTokenChanged,
  type Auth,
  type User,
} from 'firebase/auth';
import { AUTH_COOKIE, AUTH_COOKIE_MAX_AGE_S } from '../authCookie';

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

/**
 * Is there a Firebase project to talk to?
 *
 * The three fields the SDK genuinely cannot work without. Callers use this to
 * degrade honestly rather than throwing a stack trace at a judge.
 */
export const isAuthConfigured = Boolean(
  firebaseConfig.apiKey && firebaseConfig.authDomain && firebaseConfig.projectId
);

export class AuthNotConfiguredError extends Error {
  constructor() {
    super(
      'Firebase is not configured. Copy .env.local.example to .env.local and ' +
        'fill in the NEXT_PUBLIC_FIREBASE_* values.'
    );
    this.name = 'AuthNotConfiguredError';
  }
}

function app(): FirebaseApp {
  if (!isAuthConfigured) throw new AuthNotConfiguredError();
  return getApps().length ? getApp() : initializeApp(firebaseConfig);
}

export function auth(): Auth {
  return getAuth(app());
}

// ── Sign-in ───────────────────────────────────────────────────────────────

export async function signInWithEmail(email: string, password: string): Promise<User> {
  const { user } = await signInWithEmailAndPassword(auth(), email, password);
  return user;
}

export async function registerWithEmail(email: string, password: string): Promise<User> {
  const { user } = await createUserWithEmailAndPassword(auth(), email, password);
  return user;
}

export async function signInWithGoogle(): Promise<User> {
  const { user } = await signInWithPopup(auth(), new GoogleAuthProvider());
  return user;
}

export async function signOut(): Promise<void> {
  await fbSignOut(auth());
  writeAuthCookie(false);
}

// ── The optimistic-gate cookie ────────────────────────────────────────────

function writeAuthCookie(signedIn: boolean): void {
  if (typeof document === 'undefined') return;
  const base = `${AUTH_COOKIE}=1; path=/; SameSite=Lax`;
  document.cookie = signedIn
    ? `${base}; max-age=${AUTH_COOKIE_MAX_AGE_S}`
    : `${AUTH_COOKIE}=; path=/; SameSite=Lax; max-age=0`;
}

/**
 * Keep the marker cookie in step with the real session, and hand the caller
 * the current user. Returns an unsubscribe function.
 *
 * `onIdTokenChanged` rather than `onAuthStateChanged`: it also fires on the
 * hourly token refresh, which is what keeps the cookie from expiring out from
 * under a session that is still perfectly valid.
 */
export function watchAuth(onUser: (user: User | null) => void): () => void {
  if (!isAuthConfigured) {
    onUser(null);
    return () => {};
  }
  return onIdTokenChanged(auth(), (user) => {
    writeAuthCookie(Boolean(user));
    onUser(user);
  });
}

/**
 * A fresh ID token for the Authorization header, or null if signed out.
 *
 * Read from the SDK every time rather than cached anywhere: this is the value
 * route handlers verify, and a stale one fails closed.
 */
export async function getIdToken(): Promise<string | null> {
  if (!isAuthConfigured) return null;
  return (await auth().currentUser?.getIdToken()) ?? null;
}
