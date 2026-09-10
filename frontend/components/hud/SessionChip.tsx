// SessionChip.tsx — who is signed in, and the way out.
//
// Without this there is no way to sign out from the UI, which makes T-W1
// awkward to even exercise: verifying that `/dashboard` redirects when signed
// out means being able to get signed out first.
//
// Renders nothing when Firebase is unconfigured. In that state there is no
// session to show and a "Sign in" button would only lead to a page explaining
// that sign-in is switched off.
'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { isAuthConfigured, signOut, watchAuth } from '../../lib/firebase/client';
import { apiPost } from '../../lib/apiClient';

export default function SessionChip() {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!isAuthConfigured) return;
    return watchAuth((user) => {
      setEmail(user?.email ?? null);
      setReady(true);
      // Keep the users collection current (§6.14). Fire-and-forget: a profile
      // row is bookkeeping and must never block or break the dashboard.
      if (user) void apiPost('/api/users', {}).catch(() => {});
    });
  }, []);

  /**
   * Sign out, then leave.
   *
   * The proxy is a navigation-time check, so clearing the session without
   * navigating left the signed-out user sitting on the dashboard watching live
   * frames — the gate had nothing to gate. `replace` rather than `push` so Back
   * cannot return to a page this user is no longer entitled to.
   */
  const leave = async () => {
    await signOut();
    // A full load, not router.replace(): Next's client Router Cache still
    // holds this dashboard's payload, so a client-side navigation leaves it
    // one Back button away from a user who has just signed out. It also tears
    // down the WebSocket and the WebGL context, which is the honest meaning
    // of leaving.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- router.push() is the bug, not the fix
    window.location.assign('/login');
  };

  if (!isAuthConfigured || !ready || !email) return null;

  return (
    <div style={CHIP}>
      <span style={{ color: '#8b8b9e' }}>Signed in</span>
      {/* The only identifier in the chip, so the only thing set in mono. */}
      <span style={EMAIL}>{email}</span>
      <Link href="/runs" style={LINK}>
        Runs
      </Link>
      <button type="button" onClick={() => void leave()} style={BUTTON}>
        Sign out
      </button>
    </div>
  );
}

const CHIP: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  maxWidth: 420,
  padding: '8px 12px',
  borderRadius: 6,
  border: '1px solid rgba(255,255,255,0.14)',
  background: 'rgba(10, 10, 20, 0.86)',
  font: '450 12.5px/1.2 var(--ui)',
  whiteSpace: 'nowrap',
};

const EMAIL: React.CSSProperties = {
  color: '#e8e8ef',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  font: '450 12px/1.2 var(--tech)',
};

const LINK: React.CSSProperties = {
  color: '#2979FF',
  textDecoration: 'none',
  font: '600 12.5px/1.2 var(--ui)',
};

const BUTTON: React.CSSProperties = {
  padding: '4px 9px',
  borderRadius: 4,
  border: '1px solid rgba(255,255,255,0.22)',
  background: 'transparent',
  color: '#e8e8ef',
  font: '600 12.5px/1.2 var(--ui)',
  cursor: 'pointer',
};
