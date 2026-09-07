// ask.jsx — agentic answer tool. Honest working state; bimodal result; real error/retry.
const { useState: useStateA, useEffect: useEffectA, useRef: useRefA } = React;

/* ---- confidence meter ---- */
function Confidence({ confidence }) {
  const on = confidence.level === 'high' ? 3 : confidence.level === 'medium' ? 2 : 1;
  return (
    <span className={`conf ${confidence.level}`}>
      <span className="c-dots">{[0, 1, 2].map(i => <span key={i} className={`c-dot${i < on ? ' on' : ''}`} />)}</span>
      <span className="c-label">{confidence.level} confidence · {confidence.value.toFixed(2)}</span>
    </span>
  );
}

/* ---- panels ---- */
function Panel({ icon, title, count, cls, children, collapsible, openDefault = true }) {
  const [open, setOpen] = useStateA(openDefault);
  const Icon = I[icon];
  return (
    <section className={`panel ${cls || ''}`}>
      <header className="panel-head" onClick={collapsible ? () => setOpen(o => !o) : undefined}>
        <span className="ph-icon"><Icon width="16" height="16" /></span>
        <span className="ph-title">{title}</span>
        {count != null && <span className="ph-count">{count}{collapsible ? (open ? ' · hide' : ' · show') : ''}</span>}
      </header>
      {open && <div className="panel-body">{children}</div>}
    </section>
  );
}

function Provenance({ items, idx }) {
  const router = useRouter();
  return items.map((p, i) => {
    const s = idx.byId[p.id];
    if (!s) return null;
    return (
      <div key={p.id} className="prov-item" onClick={() => router.go({ view: 'statement', id: p.id })}>
        <span className="pv-num">[{i + 1}]</span>
        <div className="pv-body">
          <div className="pv-title">{s.title || s.text}</div>
          <div className="pv-role"><span style={{ color: 'var(--ink-3)' }}>{p.id}</span> · {p.role}</div>
        </div>
        <I.arrow className="pv-arrow" width="15" height="15" />
      </div>
    );
  });
}

function Trace({ steps, idx }) {
  const router = useRouter();
  return steps.map((st, i) => (
    <div key={i} className="trace-step">
      <span className="ts-phase">{st.phase}</span>
      <div>
        <div className="ts-detail">{st.detail}</div>
        {st.refs && st.refs.length > 0 && (
          <div className="ts-refs">
            {st.refs.map(rid => <span key={rid} className="ref-pill" onClick={() => router.go({ view: 'statement', id: rid })}>{rid}</span>)}
          </div>
        )}
      </div>
    </div>
  ));
}

/* ---- answered layout ---- */
function Answered({ r, idx }) {
  return (
    <div className="answer-card reveal">
      <div className="answer-top">
        <div className="answer-flags">
          <span className="flag answered"><I.check width="13" height="13" />answered</span>
          {r.degraded && <span className="flag reframed"><I.warn width="13" height="13" />degraded · forced finalize</span>}
          {r.interpretation.reframed && <span className="flag reframed"><I.warn width="13" height="13" />reframed · false premise</span>}
          <Confidence confidence={r.confidence} />
        </div>
      </div>
      <div className="answer-prose">
        {r.answer.map((p, i) => <p key={i}>{p}</p>)}
      </div>
      <div className="conf-rationale"><b>Confidence — {r.confidence.level}.</b> {r.confidence.rationale}</div>

      <div className="ask-panels" style={{ padding: '0 18px 20px' }}>
        <Panel icon="interp" title="Interpretation" cls="reveal-2">
          <div className="interp-text">
            {r.interpretation.text}
            {r.interpretation.reframed && <span className="reframe-note">⟂ {r.interpretation.reframedNote}</span>}
          </div>
        </Panel>
        <Panel icon="gap" title="Gaps" count={r.gaps.length} cls="gaps reveal-2">
          {r.gaps.map((g, i) => <div key={i} className="gap-item"><span className="gi-mark">—</span><span>{g}</span></div>)}
        </Panel>
        <Panel icon="prov" title="Provenance" count={`${r.provenance.length} statement${r.provenance.length === 1 ? '' : 's'}`} cls="reveal-3">
          <Provenance items={r.provenance} idx={idx} />
        </Panel>
        <Panel icon="trace" title="Retrieval trace" count={`${r.trace.length} steps`} cls="trace reveal-3" collapsible openDefault={false}>
          <Trace steps={r.trace} idx={idx} />
        </Panel>
      </div>
    </div>
  );
}

/* ---- needs-clarification layout ---- */
function NeedsClarification({ r, idx, onPick }) {
  return (
    <div className="clarify-card reveal">
      <div className="clarify-top">
        <div className="clarify-flag"><I.interp width="14" height="14" />needs clarification · no answer committed</div>
        <div className="clarify-q">{r.clarifyingQuestion}</div>
      </div>
      <div className="clarify-body">
        <div className="clarify-section-label">Candidate interpretations — pick one to answer</div>
        <div className="interp-options">
          {r.interpretations.map((io, i) => (
            <div key={i} className="interp-opt" onClick={() => onPick(io)}>
              <div className="io-head">
                <span className="io-name">{io.label}</span>
                <span className="io-pick">answer this →</span>
              </div>
              <div className="io-note">{io.note}</div>
              <div className="io-retrieve">
                <span className="io-rlabel">would retrieve</span>
                {io.wouldRetrieve.map(id => {
                  const s = idx.byId[id];
                  return <span key={id} className="lt" title={s ? s.title : id}>{id}</span>;
                })}
              </div>
            </div>
          ))}
        </div>
        <div className="clarify-section-label">What's known so far</div>
        <div className="known-list">
          {r.known.map((k, i) => <div key={i} className="known-item"><I.check className="ki-check" width="15" height="15" /><span>{k}</span></div>)}
        </div>
      </div>
    </div>
  );
}

/* ---- working + timeout ---- */
function Working({ elapsed, progress, onCancel }) {
  return (
    <div className="ask-working">
      <div className="aw-row">
        <div className="aw-orb"><span className="ring" /><span className="core" /></div>
        <div className="aw-text">
          <div className="aw-title">Checking the knowledge base…</div>
          <div className="aw-sub" role="status" aria-live="polite">{progress || 'Waiting for retrieval to start…'}</div>
        </div>
        <div className="aw-clock">{elapsed.toFixed(1)}s</div>
      </div>
      <button className="btn" onClick={onCancel}>Cancel</button>
      <div className="aw-bar" />
      <div className="aw-note">Progress reports completed checks. Answer text remains provisional until the result is complete.</div>
    </div>
  );
}

function AskError({ r, onRetry }) {
  return (
    <div className="ask-error reveal">
      <I.timeout className="ae-icon" width="34" height="34" />
      <div className="ae-title">{r.cancelled ? 'Ask cancelled' : 'Ask did not complete'}</div>
      <div className="ae-detail">{r.detail || 'No response within the deadline. The store is single-writer and can stall under load.'}</div>
      <div className="ae-actions">
        <button className="btn primary" onClick={onRetry}>Retry</button>
        <button className="btn" onClick={() => window.MYC_REPORT && window.MYC_REPORT()}>Report a gap</button>
      </div>
    </div>
  );
}

function AskSurface({ query }) {
  const router = useRouter();
  const idx = window.MYCELIUM_INDEX;
  const [phase, setPhase] = useStateA('idle'); // idle | working | done | error
  const [result, setResult] = useStateA(null);
  const [elapsed, setElapsed] = useStateA(0);
  const [attempt, setAttempt] = useStateA(0);
  const timers = useRefA([]);
  const active = useRefA(null);
  const [progress, setProgress] = useStateA('');
  const [partial, setPartial] = useStateA('');

  const clear = () => { timers.current.forEach(clearInterval); timers.current = []; };

  const ask = (question) => {
    if (active.current) active.current.abort();
    const controller = new AbortController(); active.current = controller;
    clear();
    setPhase('working'); setElapsed(0); setResult(null); setProgress(''); setPartial('');
    const t0 = Date.now();
    timers.current.push(setInterval(() => setElapsed((Date.now() - t0) / 1000), 100));
    window.Myc.ask(question, {
      signal: controller.signal,
      onEvent: event => {
        if (active.current !== controller) return;
        if (event.type === 'progress') setProgress(event.message);
        if (event.type === 'answer_delta') setPartial(text => text + event.text);
        if (event.type === 'answer_reset') setPartial('');
      },
    }).then(res => {
      if (active.current !== controller) return;
      clear(); setPartial(''); setResult(res); setPhase('done');
    }).catch(err => {
      if (active.current !== controller) return;
      clear();
      const cancelled = err && err.name === 'AbortError';
      const detail = cancelled ? 'The request was cancelled. Any text shown is incomplete.'
        : (err && (err.status === 401 || err.status === 403)) ? 'You need an authenticated session to ask.'
        : ((err && err.message) || 'The substrate did not respond.');
      setResult({ detail, cancelled }); setPhase('error');
    });
  };

  useEffectA(() => {
    ask(query);
    return () => { if (active.current) active.current.abort(); active.current = null; clear(); };
  }, [query, attempt]);

  // Re-ask a refined question grounded in the picked interpretation.
  const onPick = (io) => ask(`${query} — interpreted as: ${io.label}. ${io.note}`);

  const shownQuestion = (result && result.question && phase !== 'error') ? result.question : query;

  return (
    <main className="page">
      <div className="ask-stage">
        <div className="crumbs">
          <a onClick={() => router.go({ view: 'landing' })}>~</a><span className="sep">/</span>
          <span>ask</span>
        </div>

        <div className="ask-q">
          <div className="aq-label"><span className="dot" />question</div>
          <div className="aq-text">{shownQuestion || query}</div>
        </div>

        {phase === 'working' && <Working elapsed={elapsed} progress={progress} onCancel={() => active.current && active.current.abort()} />}
        {partial && phase !== 'done' && <section className="answer-card"><div className="answer-top">{phase === 'working' ? 'Composing answer · provisional' : 'Incomplete answer'}</div><div className="answer-prose" style={{ whiteSpace: 'pre-wrap' }}>{partial}</div></section>}
        {phase === 'error' && <AskError r={result} onRetry={() => setAttempt(a => a + 1)} />}
        {phase === 'done' && result && result.outcome === 'answered' && <Answered r={result} idx={idx} />}
        {phase === 'done' && result && result.outcome === 'needs_clarification' && <NeedsClarification r={result} idx={idx} onPick={onPick} />}
      </div>
    </main>
  );
}

Object.assign(window, { AskSurface });
