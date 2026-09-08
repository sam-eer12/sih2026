// login/page.tsx — the auth gate's front door (FR-36).
//
// Email/password and Google, both required by the requirement. If Firebase is
// not configured the page says so plainly and points at the file to fill in,
// rather than rendering a form whose buttons throw.
//
// The styling is the landing page's: same ink, same accent, same mono
// figures, with the neural field carried through so the transition from hero
// to sign-in does not feel like two products. The logic below — the auth
// handlers, the redirect guard, the error mapping — is unchanged.
'use client';

import { Suspense, useCallback, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import NeuralField from '../../../components/landing/NeuralField';
import {
  isAuthConfigured,
  registerWithEmail,
  signInWithEmail,
  signInWithGoogle,
  watchAuth,
} from '../../../lib/firebase/client';

/**
 * `useSearchParams()` opts a route out of static rendering unless it sits
 * inside a Suspense boundary — Next fails the build otherwise
 * (nextjs.org/docs/messages/missing-suspense-with-csr-bailout). The boundary
 * lives here so the shell can still be prerendered and only the part that
 * genuinely depends on the query string waits.
 */
export default function LoginPage() {
  return (
    <Suspense fallback={<Shell />}>
      <LoginForm />
    </Suspense>
  );
}

/** The page frame — background, field, and the centred card slot. */
function Shell({ children }: { children?: React.ReactNode }) {
  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[var(--ink-900)] p-6">
      <NeuralField
        className="pointer-events-none absolute inset-0 h-full w-full opacity-45"
        density={64}
        linkRadius={150}
      />
      {/* Pulls focus to the card without hiding the field behind it. */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse at 50% 45%, rgba(7,10,20,0) 0%, rgba(7,10,20,0.82) 62%, var(--ink-900) 100%)',
        }}
      />
      <div className="relative z-10 w-full max-w-[400px]">{children}</div>
    </main>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rise rounded-xl border border-[var(--line)] bg-[var(--ink-850)]/85 p-8 shadow-[0_24px_70px_-20px_rgba(0,0,0,0.85)] backdrop-blur-md">
      {children}
    </div>
  );
}

const INPUT =
  'mt-1.5 mb-4 w-full rounded-md border border-[var(--line)] bg-[var(--ink-800)] px-3 py-2.5 text-sm text-[var(--text-hi)] outline-none transition-colors duration-150 focus:border-[var(--accent)] placeholder:text-[var(--text-lo)]';
const LABEL =
  'block text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-lo)]';
const PRIMARY =
  'w-full rounded-md bg-[var(--accent)] px-4 py-2.5 text-sm font-semibold text-[#062713] transition-all duration-150 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50';
const SECONDARY =
  'w-full rounded-md border border-[var(--line)] px-4 py-2.5 text-sm font-semibold text-[var(--text-hi)] transition-colors duration-150 hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50';

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  // Where the proxy wanted them to end up. Only ever a same-site path.
  const next = params.get('next') ?? '/dashboard';

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The cookie the proxy reads is written by watchAuth, so a session that is
  // already live should send them straight on rather than showing a form.
  useEffect(() => {
    if (!isAuthConfigured) return;
    return watchAuth((user) => {
      if (user) router.replace(safeNext(next));
    });
  }, [router, next]);

  const run = useCallback(
    async (action: () => Promise<unknown>) => {
      setBusy(true);
      setError(null);
      try {
        await action();
        router.replace(safeNext(next));
      } catch (err) {
        setError(humanise(err));
      } finally {
        setBusy(false);
      }
    },
    [router, next]
  );

  if (!isAuthConfigured) {
    return (
      <Shell>
        <Card>
          <h1 className="text-xl font-semibold text-[var(--text-hi)]">
            Sign-in unavailable
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-[var(--text)]">
            No Firebase project is configured, so authentication is switched off and the
            dashboard is open. Copy <Code>.env.local.example</Code> to <Code>.env.local</Code>{' '}
            and fill in the <Code>NEXT_PUBLIC_FIREBASE_*</Code> values to turn it on.
          </p>
          <a href="/dashboard" className={`${PRIMARY} mt-6 block text-center`}>
            Continue to the dashboard
          </a>
        </Card>
      </Shell>
    );
  }

  return (
    <Shell>
      <Card>
        <p className="tabular text-[10px] uppercase tracking-[0.34em] text-[var(--text-lo)]">
          SIH26053 · DRDO / IDEX
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-[var(--text-hi)]">
          AVR-25D
        </h1>
        <p className="mt-2 mb-7 text-sm text-[var(--text-lo)]">
          Sign in to reach the dashboard and run history.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run(() => signInWithEmail(email, password));
          }}
        >
          <label className={LABEL} htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={INPUT}
          />

          <label className={LABEL} htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={INPUT}
          />

          {error ? (
            <p
              role="alert"
              className="mb-4 rounded-md border border-[#5a1f28] bg-[#2a0f14] px-3 py-2 text-[13px] text-[#ff8a80]"
            >
              {error}
            </p>
          ) : null}

          <button type="submit" disabled={busy} className={PRIMARY}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <button
          type="button"
          disabled={busy}
          onClick={() => void run(() => registerWithEmail(email, password))}
          className="mt-3 w-full text-[13px] text-[var(--text-lo)] underline-offset-4 transition-colors duration-150 hover:text-[var(--accent)] hover:underline disabled:opacity-50"
        >
          Create an account with this email
        </button>

        <div className="my-6 flex items-center gap-3">
          <span className="h-px flex-1 bg-[var(--line)]" />
          <span className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-lo)]">or</span>
          <span className="h-px flex-1 bg-[var(--line)]" />
        </div>

        <button
          type="button"
          disabled={busy}
          onClick={() => void run(signInWithGoogle)}
          className={SECONDARY}
        >
          Continue with Google
        </button>
      </Card>
    </Shell>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="tabular rounded bg-[var(--ink-700)] px-1.5 py-0.5 text-[12px] text-[var(--text)]">
      {children}
    </code>
  );
}

/**
 * Only ever redirect within this site.
 *
 * `next` arrives from the query string, so it is attacker-controllable: without
 * this an emailed link could bounce a freshly-signed-in user to another origin.
 */
function safeNext(next: string): string {
  return next.startsWith('/') && !next.startsWith('//') ? next : '/dashboard';
}

/** Firebase error codes are not sentences. */
function humanise(err: unknown): string {
  const code = (err as { code?: string })?.code ?? '';
  switch (code) {
    case 'auth/invalid-email':
      return 'That email address is not valid.';
    case 'auth/missing-password':
    case 'auth/weak-password':
      return 'Passwords must be at least six characters.';
    case 'auth/invalid-credential':
    case 'auth/wrong-password':
    case 'auth/user-not-found':
      return 'Email or password is incorrect.';
    case 'auth/email-already-in-use':
      return 'That email already has an account — sign in instead.';
    case 'auth/popup-closed-by-user':
      return 'The Google sign-in window was closed.';
    case 'auth/operation-not-allowed':
      return 'That sign-in method is not enabled on the Firebase project.';
    default:
      return err instanceof Error ? err.message : 'Sign-in failed.';
  }
}
