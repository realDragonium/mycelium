// Entry: check this session may read the knowledge base, then mount the app.
// The probe is the cheapest read an asker is refused, so an asker still gets
// the sign-in card here rather than an app whose screens all fail.
import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './shell';
import { errorMessage, getSubstrateCounts, isAuthError } from './api';
import { PrefsProvider } from './prefs';

type Boot = { phase: 'loading' } | { phase: 'ready' } | { phase: 'error'; error: unknown };

function Root() {
  const [boot, setBoot] = useState<Boot>({ phase: 'loading' });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    getSubstrateCounts().then(
      () => { if (live) setBoot({ phase: 'ready' }); },
      error => { if (live) setBoot({ phase: 'error', error }); },
    );
    return () => { live = false; };
  }, [attempt]);

  if (boot.phase === 'ready') return <App />;
  if (boot.phase === 'error') {
    const unauth = isAuthError(boot.error);
    const next = encodeURIComponent('/ui/' + window.location.hash);
    return (
      <div className="load-screen">
        <div className="load-card">
          <div className="load-title">{unauth ? 'Sign in to reach the knowledge base' : 'Could not load the knowledge base'}</div>
          <div className="load-detail">{unauth ? 'Mycelium needs an authenticated session.' : errorMessage(boot.error)}</div>
          {unauth
            ? <a className="btn primary" href={`/auth/login?next=${next}`}>Sign in</a>
            : <button className="btn primary" onClick={() => { setBoot({ phase: 'loading' }); setAttempt(a => a + 1); }}>Retry</button>}
        </div>
      </div>
    );
  }
  return (
    <div className="load-screen" role="status">
      <div className="load-card">
        <div className="load-orb"><span className="ring" /><span className="core" /></div>
        <div className="load-title">Loading the knowledge base…</div>
      </div>
    </div>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('index.html has no #root element');
createRoot(root).render(<PrefsProvider><Root /></PrefsProvider>);
