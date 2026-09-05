// login/page.tsx — the auth gate's front door (FR-36).
//
// Email/password and Google, both required by the requirement. If Firebase is
// not configured the page says so plainly and points at the file to fill in,
// rather than rendering a form whose buttons throw.
'use client';

import { Suspense, useCallback, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
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
    <Suspense fallback={<main style={PAGE} />}>
      <LoginForm />
    </Suspense>
  );
}

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
      <main style={PAGE}>
        <div style={CARD}>
          <h1 style={TITLE}>Sign-in unavailable</h1>
          <p style={BODY}>
            No Firebase project is configured, so authentication is switched off and the
            dashboard is open. Copy <code style={CODE}>.env.local.example</code> to{' '}
            <code style={CODE}>.env.local</code> and fill in the{' '}
            <code style={CODE}>NEXT_PUBLIC_FIREBASE_*</code> values to turn it on.
          </p>
          <a href="/dashboard" style={{ ...PRIMARY, textAlign: 'center', display: 'block' }}>
            Continue to the dashboard
          </a>
        </div>
      </main>
    );
  }

  return (
    <main style={PAGE}>
      <div style={CARD}>
        <h1 style={TITLE}>AVR-25D</h1>
        <p style={BODY}>Sign in to reach the dashboard and run history.</p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run(() => signInWithEmail(email, password));
          }}
        >
          <label style={LABEL} htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={INPUT}
          />

          <label style={LABEL} htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={INPUT}
          />

          {error ? <p style={ERROR}>{error}</p> : null}

          <button type="submit" disabled={busy} style={PRIMARY}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <button
          type="button"
          disabled={busy}
          onClick={() => void run(() => registerWithEmail(email, password))}
          style={LINK}
        >
          Create an account with this email
        </button>

        <div style={RULE}>
          <span style={RULE_TEXT}>or</span>
        </div>

        <button
          type="button"
          disabled={busy}
          onClick={() => void run(signInWithGoogle)}
          style={SECONDARY}
        >
          Continue with Google
        </button>
      </div>
    </main>
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

const PAGE: React.CSSProperties = {
  minHeight: '100vh',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: '#0b0b14',
  padding: 24,
};

const CARD: React.CSSProperties = {
  width: '100%',
  maxWidth: 380,
  padding: 28,
  borderRadius: 10,
  border: '1px solid rgba(255,255,255,0.14)',
  background: 'rgba(255,255,255,0.03)',
  color: '#e8e8ef',
  font: '14px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace',
};

const TITLE: React.CSSProperties = { margin: '0 0 6px', font: '700 24px/1.2 inherit' };
const BODY: React.CSSProperties = { margin: '0 0 20px', color: '#b9b9c8' };
const LABEL: React.CSSProperties = {
  display: 'block',
  margin: '0 0 5px',
  font: '600 11px/1 inherit',
  letterSpacing: '0.1em',
  textTransform: 'uppercase',
  color: '#8b8b9e',
};
const INPUT: React.CSSProperties = {
  width: '100%',
  padding: '10px 12px',
  marginBottom: 14,
  borderRadius: 6,
  border: '1px solid rgba(255,255,255,0.18)',
  background: 'rgba(0,0,0,0.35)',
  color: '#e8e8ef',
  font: 'inherit',
};
const PRIMARY: React.CSSProperties = {
  width: '100%',
  padding: '11px 14px',
  borderRadius: 6,
  border: 'none',
  background: '#00C853',
  color: '#04120a',
  font: '700 14px/1 inherit',
  cursor: 'pointer',
};
const SECONDARY: React.CSSProperties = {
  width: '100%',
  padding: '11px 14px',
  borderRadius: 6,
  border: '1px solid rgba(255,255,255,0.22)',
  background: 'transparent',
  color: '#e8e8ef',
  font: '600 14px/1 inherit',
  cursor: 'pointer',
};
const LINK: React.CSSProperties = {
  display: 'block',
  width: '100%',
  marginTop: 10,
  padding: 0,
  border: 'none',
  background: 'none',
  color: '#8b8b9e',
  font: '12px/1.4 inherit',
  textAlign: 'left',
  cursor: 'pointer',
  textDecoration: 'underline',
};
const RULE: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  margin: '18px 0',
  borderTop: '1px solid rgba(255,255,255,0.12)',
};
const RULE_TEXT: React.CSSProperties = {
  transform: 'translateY(-50%)',
  padding: '0 10px',
  background: '#0b0b14',
  color: '#6f6f83',
  font: '11px/1 inherit',
};
const ERROR: React.CSSProperties = {
  margin: '0 0 12px',
  padding: '8px 10px',
  borderRadius: 5,
  border: '1px solid #D50000',
  background: 'rgba(213,0,0,0.12)',
  color: '#ff8a80',
  font: '12px/1.4 inherit',
};
const CODE: React.CSSProperties = {
  padding: '1px 4px',
  borderRadius: 3,
  background: 'rgba(255,255,255,0.10)',
};
