// AuthLink.tsx — the way in, and the way out, from the front door.
//
// Nothing in the app linked to /login. The only routes there were the proxy's
// redirect and typing the URL, which meant a judge on the landing page had no
// way to sign in, and a signed-in one no way to sign out without first going
// to the dashboard. T-W1 was also awkward to exercise by hand for the same
// reason.
//
// Renders nothing at all when Firebase is unconfigured. In that state there is
// no session, and a "Sign in" link would lead only to a page explaining that
// sign-in is switched off — worse than an empty corner.
'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { isAuthConfigured, signOut, watchAuth } from '../../lib/firebase/client';

export default function AuthLink({ className = '' }: { className?: string }) {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  // Until the SDK has spoken we know nothing, and guessing flashes the wrong
  // label on every load — "Sign in" for a second at a signed-in user.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!isAuthConfigured) return;
    return watchAuth((user) => {
      setEmail(user?.email ?? null);
      setReady(true);
    });
  }, []);

  if (!isAuthConfigured || !ready) return null;

  if (!email) {
    return (
      <Link href="/login" className={`${LINK} ${className}`}>
        Sign in
      </Link>
    );
  }

  return (
    <div className={`flex items-center gap-3.5 ${className}`}>
      {/* An address is an identifier, so mono — and truncated rather than
          allowed to push the control off a narrow screen. */}
      <span className="tabular max-w-[180px] truncate text-[12.5px] text-[var(--text-lo)]">
        {email}
      </span>
      <button
        type="button"
        onClick={() => {
          // Same reason as the dashboard chip: the gate is a navigation-time
          // check, so leaving is part of signing out.
          void signOut().then(() => router.replace('/login'));
        }}
        className={LINK}
      >
        Sign out
      </button>
    </div>
  );
}

const LINK =
  'text-[13px] font-medium text-[var(--text-lo)] underline-offset-4 transition-colors duration-150 hover:text-[var(--accent)] hover:underline';
  