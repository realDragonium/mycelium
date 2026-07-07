// app.jsx — shell: router, command bar (Ask | Find), landing, tweaks.
const { useState: useStateApp, useEffect: useEffectApp, useMemo: useMemoApp, useRef: useRefApp } = React;

function useRouterState() {
  const [route, setRoute] = useStateApp(parseHash);
  useEffectApp(() => {
    const on = () => setRoute(parseHash());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  const go = (next) => {
    const h = routeToHash(next);
    if (h === (window.location.hash || '#/')) setRoute(next);
    window.location.hash = h;
    window.scrollTo({ top: 0, behavior: 'instant' });
  };
  return { ...route, go };
}

/* ---------------- Command bar ---------------- */
function CommandBar({ variant }) {
  const router = useRouter();
  const inputRef = useRefApp(null);
  const seedIntent = router.view === 'find' ? 'find' : 'ask';
  const [intent, setIntent] = useStateApp(seedIntent);
  const [value, setValue] = useStateApp(router.query || '');
  const [findMode, setFindMode] = useStateApp(router.mode || 'semantic');

  useEffectApp(() => {
    setIntent(router.view === 'find' ? 'find' : 'ask');
    if (router.view === 'find' || router.view === 'ask') setValue(router.query || '');
    if (router.view === 'find') setFindMode(router.mode || 'semantic');
  }, [router.view, router.query, router.mode]);

  useEffectApp(() => {
    const on = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); inputRef.current?.focus(); inputRef.current?.select(); }
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, []);

  const submit = (e) => {
    e?.preventDefault();
    if (!value.trim()) return;
    if (intent === 'ask') router.go({ view: 'ask', query: value });
    else router.go({ view: 'find', query: value, mode: findMode });
  };

  return (
    <div className="cmd-wrap">
      <form className="cmd" data-intent={intent} onSubmit={submit}>
        <div className="cmd-toggle">
          <button type="button" className={`cmd-mode${intent === 'ask' ? ' on' : ''}`} data-tier="ask" onClick={() => setIntent('ask')}>
            <span className="m-name">Ask</span><span className="m-sub">agentic</span>
          </button>
          <button type="button" className={`cmd-mode${intent === 'find' ? ' on' : ''}`} data-tier="find" onClick={() => setIntent('find')}>
            <span className="m-name">Find</span><span className="m-sub">deterministic</span>
          </button>
        </div>
        <div className="cmd-field">
          <span className="lead">{intent === 'ask' ? <I.ask width="20" height="20" /> : <I.find width="18" height="18" />}</span>
          <input
            ref={inputRef}
            value={value}
            onChange={e => setValue(e.target.value)}
            placeholder={intent === 'ask' ? 'Ask the substrate a question…' : 'Find statements by meaning, text, or breadth…'}
            spellCheck={false}
            autoFocus={variant === 'hero'}
          />
        </div>
        <button type="submit" className="cmd-go">{intent === 'ask' ? 'Reason' : 'Search'}<span className="kbd">↵</span></button>
      </form>

      {variant === 'hero' && intent === 'find' && (
        <FindLanes mode={findMode} query={value} onMode={setFindMode} />
      )}
    </div>
  );
}

/* ---------------- Landing ---------------- */
const EXAMPLES = [
  { intent: 'ask', q: 'How does a query get from Claude to an answer?', tag: 'answered + provenance' },
  { intent: 'ask', q: 'Is it fast?', tag: 'needs clarification' },
  { intent: 'ask', q: 'Which graph database engine does Mycelium use?', tag: 'reframes a false premise' },
  { intent: 'find', mode: 'grep', q: 'HNSW', tag: 'grep · alias-aware' },
  { intent: 'find', mode: 'survey', q: 'how are writes validated', tag: 'survey · long tail' },
  { intent: 'find', mode: 'semantic', q: 'reranker', tag: 'semantic · scored' },
];

function Landing() {
  const router = useRouter();
  const data = window.MYCELIUM_DATA;
  const run = (ex) => ex.intent === 'ask' ? router.go({ view: 'ask', query: ex.q }) : router.go({ view: 'find', query: ex.q, mode: ex.mode });
  const ingest = () => window.MYC_GO_INGEST(null);

  return (
    <main className="page landing">
      <div className="landing-hero">
        <div className="landing-eyebrow">Mycelium · human cockpit</div>
        <h1 className="landing-title">Interrogate a substrate<br />built to be <em>read by machines</em>.</h1>
        <p className="landing-blurb">Knowledge enters by <b style={{ color: 'var(--ink-2)' }}>ingest</b> — drop in raw text, an agent structures it. Read it back two ways: <b style={{ color: 'var(--ink-2)' }}>Ask</b> for a reasoned answer with its gaps and provenance, or <b style={{ color: 'var(--ink-2)' }}>Find</b> for raw, scored matches you judge.</p>
      </div>

      <div className="landing-cmd"><CommandBar variant="hero" /></div>

      <div className="ingest-promo" onClick={ingest}>
        <div className="ip-icon"><I.ingest width="20" height="20" /></div>
        <div>
          <div className="ip-name">Ingest raw text<span className="ip-tag">write · primary path</span></div>
          <div className="ip-desc">Paste a brain-dump, doc, or transcript — the librarian extracts a draft you review before anything is written.</div>
        </div>
        <span className="ip-go"><I.ingest width="15" height="15" />Start ingest</span>
      </div>

      <div className="landing-tier-note">
        <div className="tier-card ask">
          <div className="tc-head"><span className="tc-dot" /><span className="tc-name">Ask</span><span className="tc-kind">agentic · slow</span></div>
          <div className="tc-desc">A multi-second reasoning loop returns one answer — with confidence, the interpretation it used, explicit gaps, provenance, and a trace.</div>
        </div>
        <div className="tier-card find">
          <div className="tc-head"><span className="tc-dot" /><span className="tc-name">Find</span><span className="tc-kind">deterministic · fast</span></div>
          <div className="tc-desc">Three primitives — semantic, grep, survey — return raw statements with relevance scores. Nothing is hidden; the long tail is shown, faded.</div>
        </div>
      </div>

      <div className="landing-examples">
        <div className="examples-head">try one</div>
        {EXAMPLES.map((ex, i) => (
          <div key={i} className={`example-row ${ex.intent}`} onClick={() => run(ex)}>
            <span className={`ex-badge ${ex.intent}`}>{ex.intent}</span>
            <span className="ex-q">{ex.q}</span>
            <span className="ex-q" style={{ flex: 'none', fontFamily: 'var(--mono)', fontSize: 'var(--fs-2xs)', color: 'var(--ink-4)', fontStyle: 'normal' }}>{ex.tag}</span>
            <I.arrow className="ex-arrow" width="16" height="16" />
          </div>
        ))}
      </div>

      <div className="landing-stats">
        <div className="lstat"><div className="ls-n">{data.statements.length}</div><div className="ls-l">statements</div></div>
        <div className="lstat"><div className="ls-n">{data.entities.length}</div><div className="ls-l">entities</div></div>
        <div className="lstat"><div className="ls-n">{data.names.length}</div><div className="ls-l">names</div></div>
        <div className="lstat"><div className="ls-n">{data.links.length}</div><div className="ls-l">links</div></div>
        <div className="lstat"><div className="ls-n">{data.statementKinds.length}</div><div className="ls-l">kinds</div></div>
      </div>
    </main>
  );
}

/* ---------------- App ---------------- */
function App() {
  const router = useRouterState();
  const data = window.MYCELIUM_DATA;
  useMemoApp(() => { window.MYCELIUM_INDEX = buildIndex(data); }, [data]);
  const [igNonce, setIgNonce] = useStateApp(0);
  window.MYC_GO_INGEST = (seed) => { window.MYC_INGEST_SEED = seed || null; setIgNonce(n => n + 1); router.go({ view: 'ingest' }); };

  const defaults = window.MYC_TWEAKS;
  const [t, setTweak] = useTweaks(defaults);
  const draftsArr = window.useMycDrafts ? window.useMycDrafts() : [];
  const openDrafts = draftsArr.filter(d => d.status === 'open').length;
  const pendingArr = window.useMycPending ? window.useMycPending() : null;
  const openMentions = (pendingArr || []).filter(p => p.status === 'open').length;

  useEffectApp(() => {
    const r = document.documentElement;
    r.dataset.theme = t.theme || 'dark';
    r.dataset.density = t.density || 'comfortable';
    r.dataset.answerVoice = t.answerVoice || 'serif';
    if (t.accent) r.style.setProperty('--bio', t.accent); else r.style.removeProperty('--bio');
  }, [t.theme, t.density, t.answerVoice, t.accent]);

  let screen;
  switch (router.view) {
    case 'find': screen = <FindResults query={router.query} mode={router.mode} />; break;
    case 'ask': screen = <AskSurface key={router.query} query={router.query} />; break;
    case 'ingest': screen = <IngestSurface key={igNonce} />; break;
    case 'coverage': screen = <CoverageScreen />; break;
    case 'mentions': screen = <MentionsScreen />; break;
    case 'drafts': screen = <DraftsList />; break;
    case 'draft': screen = <DraftReview id={router.id} />; break;
    case 'statement': screen = <StatementDetail id={router.id} />; break;
    case 'entity': screen = <EntityDetail id={router.id} />; break;
    default: screen = <Landing />;
  }

  const isLanding = router.view === 'landing';

  return (
    <RouterCtx.Provider value={router}>
      <div className="shell">
        <header className="topbar">
          <div className="topbar-inner">
            <div className="brand" onClick={() => router.go({ view: 'landing' })}>
              <I.brand className="brand-mark" />
              <span className="brand-name">Mycelium</span>
              <span className="brand-tag">cockpit</span>
            </div>
            <div className="topbar-spacer" />
            <button className={`nav-btn${router.view === 'coverage' ? ' on' : ''}`} onClick={() => router.go({ view: 'coverage' })}><I.gap width="15" height="15" />Coverage{window.MYCELIUM_COVERAGE && window.MYCELIUM_COVERAGE.summary.gaps > 0 && <span className="nb-badge">{window.MYCELIUM_COVERAGE.summary.gaps}</span>}</button>
            <button className={`nav-btn${router.view === 'mentions' ? ' on' : ''}`} onClick={() => router.go({ view: 'mentions' })}><I.interp width="15" height="15" />Mentions{openMentions > 0 && <span className="nb-badge">{openMentions}</span>}</button>
            <button className={`drafts-btn${openDrafts ? ' has-open' : ''}`} onClick={() => router.go({ view: 'drafts' })}><I.prov width="15" height="15" />Drafts{openDrafts > 0 && <span className="db-badge">{openDrafts}</span>}</button>
            <button className="ingest-btn" onClick={() => window.MYC_GO_INGEST(null)}><I.ingest width="15" height="15" />Ingest</button>
            {isLanding && <div className="topbar-meta">
              <span><span className="dot" style={{ display: 'inline-block', marginRight: 6 }} /><b>writes</b> → drafts</span>
            </div>}
          </div>
        </header>

        {screen}

        <footer className="foot">
          <div className="fi">
            <span>mycelium <b>v0.2</b> · human cockpit · {data.statements.length + data.entities.length + data.names.length} records</span>
            <span>substrate: <b>single-writer</b> · naive · can time out</span>
          </div>
        </footer>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Appearance" />
        <TweakRadio label="Theme" value={t.theme} options={['dark', 'light']} onChange={v => setTweak('theme', v)} />
        <TweakRadio label="Density" value={t.density} options={['compact', 'comfortable', 'roomy']} onChange={v => setTweak('density', v)} />
        <TweakSection label="Read tiers" />
        <TweakRadio label="Ask voice" value={t.answerVoice} options={['serif', 'sans']} onChange={v => setTweak('answerVoice', v)} />
        <TweakColor label="Mycelium accent" value={t.accent}
          options={['oklch(0.875 0.185 146)', 'oklch(0.9 0.19 122)', 'oklch(0.85 0.12 178)', 'oklch(0.84 0.15 78)']}
          onChange={v => setTweak('accent', v)} />
        <div style={{ padding: '12px 16px', fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--ink-4)', lineHeight: 1.6, borderTop: '1px solid var(--line)' }}>
          Ask = serif synthesis (green). Find = mono substrate (cyan). Type & color encode the two read tiers.
        </div>
      </TweaksPanel>
    </RouterCtx.Provider>
  );
}

/* ---------------- Startup: load the live substrate before mounting the app ---------------- */
function AppRoot() {
  const [state, setState] = useStateApp('loading'); // loading | ready | error
  const [err, setErr] = useStateApp(null);

  const load = () => {
    setState('loading'); setErr(null);
    window.Myc.loadData()
      .then(() => setState('ready'))
      .catch((e) => { setErr(e); setState('error'); });
  };
  useEffectApp(() => { load(); }, []);

  if (state === 'ready') return <App />;

  if (state === 'error') {
    const unauth = err && (err.status === 401 || err.status === 403);
    return (
      <div className="load-screen">
        <div className="load-card">
          <div className="load-title">{unauth ? 'Sign in to reach the substrate' : 'Could not load the substrate'}</div>
          <div className="load-detail">{unauth
            ? 'The cockpit reads the live substrate, which requires an authenticated session.'
            : String((err && err.message) || err || 'unknown error')}</div>
          <div className="load-actions">
            {unauth
              ? <a className="load-btn primary" href="/auth/login?next=/cockpit/">Sign in</a>
              : <button className="load-btn primary" onClick={load}>Retry</button>}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="load-screen">
      <div className="load-card">
        <div className="load-orb"><span className="ring" /><span className="core" /></div>
        <div className="load-title">Loading the substrate…</div>
        <div className="load-detail">fetching entities, statements, links & vocabularies</div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<AppRoot />);
