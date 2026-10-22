// research.jsx — topic → source-backed research run → optional draft handoff.
const { useState: useStateR, useEffect: useEffectR, useRef: useRefR } = React;

function researchRelTime(ts) {
  const t = Date.parse(ts);
  if (!t || isNaN(t)) return '';
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

function researchStatusStyle(status) {
  if (status === 'draft_created') return { color: 'var(--bio)', border: '1px solid var(--bio-line)', background: 'var(--bio-bg)' };
  if (status === 'failed') return { color: 'var(--danger)', border: '1px solid var(--danger)', background: 'color-mix(in oklab, var(--danger) 8%, transparent)' };
  if (status === 'queued' || status === 'running') return { color: 'var(--cyan)', border: '1px solid var(--cyan-line)', background: 'var(--cyan-bg)' };
  return { color: 'var(--ink-3)', border: '1px solid var(--line)', background: 'var(--bg-2)' };
}

function researchDotStyle(status) {
  if (status === 'draft_created') return { background: 'var(--bio)', boxShadow: '0 0 8px var(--bio-glow)' };
  if (status === 'failed') return { background: 'var(--danger)' };
  if (status === 'queued' || status === 'running') return { background: 'var(--cyan)' };
  return { background: 'var(--ink-4)' };
}

function ResearchSurface() {
  const router = useRouter();
  const [topic, setTopic] = useStateR('');
  const [source, setSource] = useStateR('');
  const [sources, setSources] = useStateR([]);
  const [runs, setRuns] = useStateR([]);
  const [loading, setLoading] = useStateR(true);
  const [busy, setBusy] = useStateR(false);
  const [err, setErr] = useStateR(null);
  const alive = useRefR(true);
  const inFlight = useRefR(false);
  const needsRefresh = useRefR(false);

  const refresh = () => {
    if (inFlight.current) { needsRefresh.current = true; return Promise.resolve(); }
    inFlight.current = true;
    return Myc.research.list()
      .then(rs => { if (alive.current) setRuns(rs || []); })
      .catch(e => { if (alive.current) setErr((e && e.message) || 'Could not load research runs.'); })
      .finally(() => {
        inFlight.current = false;
        if (alive.current) setLoading(false);
        if (alive.current && needsRefresh.current) { needsRefresh.current = false; return refresh(); }
      });
  };

  useEffectR(() => {
    alive.current = true;
    Myc.research.sources()
      .then(ss => {
        if (!alive.current) return;
        setSources(ss || []);
        if ((ss || []).length === 1) setSource(ss[0].name);
      })
      .catch(e => { if (alive.current) setErr((e && e.message) || 'Could not load research sources.'); });
    refresh();
    return () => { alive.current = false; };
  }, []);

  useEffectR(() => {
    if (!runs.some(r => r.status === 'queued' || r.status === 'running')) return;
    const t = setInterval(() => refresh(), 2500);
    return () => clearInterval(t);
  }, [runs]);

  const start = () => {
    const q = topic.trim();
    if (!q || !source || busy) return;
    setBusy(true); setErr(null);
    Myc.research.start(q, source)
      .then(() => { if (!alive.current) return; setTopic(''); return refresh(); })
      .catch(e => {
        if (!alive.current) return;
        const msg = e && e.status === 403
          ? 'You need drafter access to start research runs.'
          : (e && e.message) || 'Research failed.';
        setErr(msg);
      })
      .finally(() => { if (alive.current) setBusy(false); });
  };

  const hasSources = sources.length > 0;

  return (
    <main className="page narrow"><div className="ingest-stage">
      <div className="crumbs"><a onClick={() => router.go({ view: 'landing' })}>~</a><span className="sep">/</span><span>research</span></div>
      <h1 className="ingest-title">Research a topic. Let the <em>librarian</em> draft what it finds.</h1>
      <p className="ingest-sub">Pick a configured source, describe the question, and start a server-side run. Completed runs can hand you a draft for review.</p>

      <div className="src-type-row">
        <span className="stl">source</span>
        {sources.map(s => (
          <button key={s.name} className={`src-chip${source === s.name ? ' on' : ''}`} onClick={() => setSource(s.name)}><I.find className="sc-glyph" />{s.name}</button>
        ))}
        {!hasSources && <span className="ingest-hint" style={{ marginTop: 0 }}>No sources configured — set MYCELIUM_SOURCES</span>}
      </div>

      <div className="ingest-field">
        <textarea value={topic} onChange={e => setTopic(e.target.value)} spellCheck={false} placeholder={'What should be researched? e.g. "how invite reminders are scheduled"'} />
        <div className="ingest-foot">
          <span className="if-meta"><b>{topic.trim() ? topic.trim().split(/\s+/).length : 0}</b> words</span>
          <span className="if-spacer" />
          <button className="btn extract" disabled={!topic.trim() || !source || busy || !hasSources} onClick={start}><I.ask width="15" height="15" />{busy ? 'Starting…' : 'Start research'}</button>
        </div>
      </div>
      {err && <div className="stmt-edit-err">{err}</div>}

      <div className="drafts-head" style={{ marginTop: 28 }}>
        <h1>Runs</h1>
        <span className="dh-sub">{loading ? 'loading…' : 'newest first'}</span>
      </div>

      {runs.length === 0 ? <div style={{ marginTop: 24 }}><EmptyState title="No research runs yet." blurb="Start a run to populate this queue." /></div> : (
        <div className="draft-list">
          {runs.map(run => (
            <div key={run.id} className="draft-row" style={{ cursor: 'default' }}>
              <span className="dr-dot" style={researchDotStyle(run.status)} />
              <div className="dr-body">
                <div className="dr-title">{run.topic || 'Untitled research run'}</div>
                <div className="dr-meta">
                  <span className="did">{run.id}</span><span>·</span><span>{run.source || 'source'}</span><span>·</span><span>{researchRelTime(run.created_at)}</span>
                  {(run.status === 'failed' || run.status === 'nothing_found') && run.error && <><span>·</span><span className="flag">{run.error}</span></>}
                </div>
              </div>
              <span className="st-badge" style={researchStatusStyle(run.status)}>{run.status}</span>
              {run.status === 'draft_created' && run.draft_id
                ? <button className="stmt-edit-btn" onClick={() => router.go({ view: 'draft', id: run.draft_id })}><I.prov width="13" height="13" />View draft</button>
                : <span className="dr-time">{run.finished_at ? researchRelTime(run.finished_at) : ''}</span>}
            </div>
          ))}
        </div>
      )}
    </div></main>
  );
}

Object.assign(window, { ResearchSurface });
