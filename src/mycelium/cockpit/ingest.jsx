// ingest.jsx — bulk text ingest (write tier): compose → async extraction → hands a draft to the store.
const { useState: useStateIg, useEffect: useEffectIg, useRef: useRefIg, useMemo: useMemoIg } = React;

const SOURCE_TYPES = [
  { k: 'brain-dump', label: 'Brain-dump', glyph: 'survey' },
  { k: 'pasted-doc', label: 'Pasted doc', glyph: 'grep' },
  { k: 'transcript', label: 'Transcript', glyph: 'interp' },
  { k: 'code', label: 'Codebase', glyph: 'trace' },
];
const PHASES = [
  { k: 'read', label: 'Reading source' },
  { k: 'extract', label: 'Extracting entities & statements' },
  { k: 'resolve', label: 'Resolving names & links against the substrate' },
  { k: 'assemble', label: 'Assembling draft' },
];

function IngestSurface() {
  const router = useRouter();
  const seed = useMemoIg(() => { const s = window.MYC_INGEST_SEED; window.MYC_INGEST_SEED = null; return s; }, []);
  const [phase, setPhase] = useStateIg('compose');     // compose | processing
  const [source, setSource] = useStateIg(seed?.source || '');
  const [sourceType, setSourceType] = useStateIg(seed?.sourceType || 'brain-dump');
  const [activeIdx, setActiveIdx] = useStateIg(0);
  const [elapsed, setElapsed] = useStateIg(0);
  const [outcome, setOutcome] = useStateIg(null);      // null | { kind:'nothing', reason } | { kind:'error', message }
  const timers = useRefIg([]);
  const alive = useRefIg(true);
  const clear = () => { timers.current.forEach(clearTimeout); timers.current.forEach(clearInterval); timers.current = []; };

  useEffectIg(() => () => { alive.current = false; }, []);

  const startExtract = () => {
    if (!source.trim()) return;
    setPhase('processing'); setActiveIdx(0); setElapsed(0); setOutcome(null);
    const t0 = Date.now();
    // Real elapsed timer.
    const tick = setInterval(() => setElapsed((Date.now() - t0) / 1000), 100);
    timers.current.push(tick);
    // Indeterminate visual flavour: gently cycle the active phase for liveliness.
    // This is NOT progress — the real outcome is the promise below.
    const cycle = setInterval(() => setActiveIdx(i => (i + 1) % PHASES.length), 2600);
    timers.current.push(cycle);

    Myc.ingest(source).then((res) => {
      if (!alive.current) return;
      clear();
      if (res && res.outcome === 'draft_created') {
        router.go({ view: 'draft', id: res.draft_id });
        return;
      }
      // nothing_to_ingest — the substrate found nothing worth a draft.
      setOutcome({ kind: 'nothing', reason: (res && res.reason) || 'The librarian found nothing worth drafting from this text.' });
    }).catch((err) => {
      if (!alive.current) return;
      clear();
      const msg = err && err.status === 403
        ? 'You need drafter/writer access to ingest.'
        : (err && err.message) || 'Ingest failed.';
      setOutcome({ kind: 'error', message: msg });
    });
  };

  useEffectIg(() => { if (seed && seed.auto && seed.source) startExtract(); return clear; /* eslint-disable-next-line */ }, []);

  if (phase === 'processing') {
    return (
      <main className="page"><div className="ingest-stage">
        <div className="crumbs"><a onClick={() => router.go({ view: 'landing' })}>~</a><span className="sep">/</span><span>ingest</span><span className="sep">/</span><span className="here">extracting</span></div>
        {outcome && outcome.kind === 'nothing' ? (
          <div className="ingest-proc">
            <EmptyState title="Nothing to ingest" blurb={outcome.reason} />
            <div className="ip-leave-note" style={{ justifyContent: 'center' }}>
              <button className="btn" onClick={() => { setOutcome(null); setPhase('compose'); }}>Back to compose</button>
            </div>
          </div>
        ) : outcome && outcome.kind === 'error' ? (
          <div className="ingest-proc">
            <EmptyState title="Ingest failed" blurb={outcome.message} />
            <div className="ip-leave-note" style={{ justifyContent: 'center' }}>
              <button className="btn" onClick={() => { setOutcome(null); setPhase('compose'); }}>Back to compose</button>
            </div>
          </div>
        ) : (
          <div className="ingest-proc">
            <div className="ip-top">
              <div className="ip-orb"><span className="ring" /><span className="core" /></div>
              <div className="ip-headline"><div className="h">The librarian is reading your {sourceType.replace('-', ' ')}…</div><div className="s">server-side extraction · emits a draft for your review</div></div>
              <div className="ip-clock">{elapsed.toFixed(1)}s</div>
            </div>
            <div className="ip-phases">
              {PHASES.map((ph, i) => (
                <div key={ph.k} className={`ip-phase${i === activeIdx ? ' active' : ''}`}>
                  <span className="pp-mark" />
                  <span>{ph.label}</span>
                  <span className="pp-t">{i === activeIdx ? 'working' : 'queued'}</span>
                </div>
              ))}
            </div>
            <div className="ip-leave-note"><I.timeout className="lc" width="16" height="16" /><span>This may take a while. You're free to navigate away — the draft will be waiting under your drafts when extraction completes.</span></div>
          </div>
        )}
      </div></main>
    );
  }

  // compose
  return (
    <main className="page"><div className="ingest-stage">
      <div className="crumbs"><a onClick={() => router.go({ view: 'landing' })}>~</a><span className="sep">/</span><span>ingest</span></div>
      <h1 className="ingest-title">Drop in raw text. The <em>librarian</em> structures it.</h1>
      <p className="ingest-sub">Paste a brain-dump, a doc, or a transcript. A server-side agent decides the entities, statements, kinds, links, and mentions — then hands you a <b>draft to review</b>. You never structure the knowledge by hand, and nothing is written until you submit.</p>

      <div className="src-type-row">
        <span className="stl">source</span>
        {SOURCE_TYPES.map(st => { const G = I[st.glyph]; return (
          <button key={st.k} className={`src-chip${sourceType === st.k ? ' on' : ''}`} onClick={() => setSourceType(st.k)}><G className="sc-glyph" />{st.label}</button>); })}
      </div>

      <div className="ingest-field">
        <textarea value={source} onChange={e => setSource(e.target.value)} spellCheck={false} placeholder="Paste raw text here — the more context, the richer the extracted draft…" />
        <div className="ingest-foot">
          <span className="if-meta"><b>{source.trim() ? source.trim().split(/\s+/).length : 0}</b> words · <b>{source.length}</b> chars</span>
          <span className="if-spacer" />
          <button className="btn extract" disabled={!source.trim()} onClick={startExtract}><I.ask width="15" height="15" />Extract to draft</button>
        </div>
      </div>
      <div className="ingest-hint">// extraction is server-side and long-running — you can leave and come back; the draft is waiting under your drafts when it's done.</div>
    </div></main>
  );
}

Object.assign(window, { IngestSurface });
