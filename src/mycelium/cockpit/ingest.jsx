// ingest.jsx — bulk text ingest (write tier). Two modes over one textarea:
//   librarian — LLM extraction (async, long-running) → draft
//   rules     — deterministic split & link (`ingest_text`, seconds) → draft + in-place result table
// Both hand a draft to the store; nothing is written until it is approved.
const { useState: useStateIg, useEffect: useEffectIg, useRef: useRefIg, useMemo: useMemoIg } = React;

const SOURCE_TYPES = [
  { k: 'brain-dump', label: 'Brain-dump', glyph: 'survey' },
  { k: 'pasted-doc', label: 'Pasted doc', glyph: 'grep' },
  { k: 'transcript', label: 'Transcript', glyph: 'interp' },
  { k: 'code', label: 'Codebase', glyph: 'trace' },
];
const INGEST_MODES = [
  { k: 'librarian', label: 'Librarian', sub: 'LLM extraction' },
  { k: 'rules', label: 'Rules', sub: 'split & link' },
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
  const [phase, setPhase] = useStateIg('compose');     // compose | processing | rules-busy | rules-result
  const [mode, setMode] = useStateIg(seed?.mode === 'rules' ? 'rules' : 'librarian');
  const [rulesOut, setRulesOut] = useStateIg(null);    // { res, draft } from ingest_text + the draft it created
  const [source, setSource] = useStateIg(seed?.source || '');
  const [sourceType, setSourceType] = useStateIg(seed?.sourceType || 'brain-dump');
  const [activeIdx, setActiveIdx] = useStateIg(0);
  const [elapsed, setElapsed] = useStateIg(0);
  const [outcome, setOutcome] = useStateIg(null);      // null | { kind:'nothing', reason } | { kind:'error', message }
  const timers = useRefIg([]);
  const alive = useRefIg(true);
  const runId = useRefIg(0);                           // bumps per run; a response from an older run is ignored
  const busy = phase === 'processing' || phase === 'rules-busy';
  const clear = () => { timers.current.forEach(clearTimeout); timers.current.forEach(clearInterval); timers.current = []; };

  useEffectIg(() => () => { alive.current = false; }, []);

  const startExtract = () => {
    if (!source.trim() || busy) return;
    const mine = ++runId.current;
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
      if (!alive.current || mine !== runId.current) return;
      clear();
      if (res && res.outcome === 'draft_created') {
        router.go({ view: 'draft', id: res.draft_id });
        return;
      }
      // nothing_to_ingest — the substrate found nothing worth a draft.
      setOutcome({ kind: 'nothing', reason: (res && res.reason) || 'The librarian found nothing worth drafting from this text.' });
    }).catch((err) => {
      if (!alive.current || mine !== runId.current) return;
      clear();
      const msg = err && err.status === 403
        ? 'You need drafter/writer access to ingest.'
        : (err && err.message) || 'Ingest failed.';
      setOutcome({ kind: 'error', message: msg });
    });
  };

  const startRules = () => {
    if (!source.trim() || busy) return;
    const mine = ++runId.current;
    setPhase('rules-busy'); setOutcome(null); setRulesOut(null);
    Myc.ingestText(source).then(async (res) => {
      // The server created the draft whether or not this screen is still mounted;
      // the global Drafts list/badge is cached at mount, so refresh it regardless.
      if (res && res.draft_id && typeof refreshDrafts === 'function') refreshDrafts();
      if (!alive.current || mine !== runId.current) return;
      // The draft is the record: input-derived links (requires from a
      // when-clause, proceeds from an "and then" cut) live only on its batch op.
      let draft = null;
      if (res && res.draft_id) {
        try { const d = await Myc.drafts.get(res.draft_id); draft = d && d.draft; } catch (e) { /* summary still renders */ }
      }
      if (!alive.current || mine !== runId.current) return;
      setRulesOut({ res, draft }); setPhase('rules-result');
    }).catch((err) => {
      if (!alive.current || mine !== runId.current) return;
      const msg = err && err.status === 403 ? 'You need drafter/writer access to ingest.' : (err && err.message) || 'Split & link failed.';
      setOutcome({ kind: 'error', message: msg }); setPhase('compose');
    });
  };

  useEffectIg(() => { if (seed && seed.auto && seed.source) { if (seed.mode === 'rules') startRules(); else startExtract(); } return clear; /* eslint-disable-next-line */ }, []);

  if (phase === 'rules-result' && rulesOut) {
    return (
      <main className="page"><div className="ingest-stage">
        <div className="crumbs"><a onClick={() => router.go({ view: 'landing' })}>~</a><span className="sep">/</span><span>ingest</span><span className="sep">/</span><span className="here">split & link</span></div>
        <RulesResult res={rulesOut.res} draft={rulesOut.draft}
          onOpen={() => rulesOut.res.draft_id && router.go({ view: 'draft', id: rulesOut.res.draft_id })}
          onAgain={() => { setRulesOut(null); setPhase('compose'); }} />
      </div></main>
    );
  }

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
      <div className="ingest-mode" role="radiogroup" aria-label="Ingest mode">
        {INGEST_MODES.map(m => (
          <button key={m.k} role="radio" aria-checked={mode === m.k} disabled={busy} className={`im-opt${mode === m.k ? ' on' : ''}`} onClick={() => { if (busy) return; setMode(m.k); setOutcome(null); }}>
            <span className="im-l">{m.label}</span><span className="im-s">{m.sub}</span>
          </button>
        ))}
      </div>
      {mode === 'librarian' ? (<>
        <h1 className="ingest-title">Drop in raw text. The <em>librarian</em> structures it.</h1>
        <p className="ingest-sub">Paste a brain-dump, a doc, or a transcript. A server-side agent decides the entities, statements, kinds, links, and mentions — then hands you a <b>draft to review</b>. You never structure the knowledge by hand, and nothing is written until you submit.</p>
        <div className="src-type-row">
          <span className="stl">source</span>
          {SOURCE_TYPES.map(st => { const G = I[st.glyph]; return (
            <button key={st.k} className={`src-chip${sourceType === st.k ? ' on' : ''}`} onClick={() => setSourceType(st.k)}><G className="sc-glyph" />{st.label}</button>); })}
        </div>
      </>) : (<>
        <h1 className="ingest-title">Drop in statement-like text. The <em>rules</em> split and link it.</h1>
        <p className="ingest-sub">No model in the write path: catalog cues split sentences, phrasing shapes assign kinds, and the connection pipeline proposes links, merges and contradictions against what the substrate already holds. What the rules cannot resolve is <b>flagged, never guessed</b>. You get one open draft.</p>
      </>)}
      {outcome && outcome.kind === 'error' && <div className="ingest-error">{outcome.message}</div>}

      <div className="ingest-field">
        <textarea value={source} onChange={e => setSource(e.target.value)} spellCheck={false} disabled={busy}
          placeholder={mode === 'rules' ? 'Paste sentences or short bullets — one claim per clause splits best. Conditionals, "and", "and then", and lists are cut on the catalog\'s own cues…' : 'Paste raw text here — the more context, the richer the extracted draft…'} />
        <div className="ingest-foot">
          <span className="if-meta"><b>{source.trim() ? source.trim().split(/\s+/).length : 0}</b> words · <b>{source.length}</b> chars</span>
          <span className="if-spacer" />
          {mode === 'rules'
            ? <button className="btn extract" disabled={!source.trim() || busy} onClick={startRules}><I.ingest width="15" height="15" />{phase === 'rules-busy' ? 'Splitting & linking…' : 'Split & link to draft'}</button>
            : <button className="btn extract" disabled={!source.trim() || busy} onClick={startExtract}><I.ask width="15" height="15" />Extract to draft</button>}
        </div>
      </div>
      {mode === 'rules'
        ? <div className="ingest-hint">// deterministic and quick — the result shows every fragment, its kind or flag, and the connections it got, then opens the draft.</div>
        : <div className="ingest-hint">// extraction is server-side and long-running — you can leave and come back; the draft is waiting under your drafts when it's done.</div>}
    </div></main>
  );
}

// --- rules result -------------------------------------------------------------
// One table, one row per fragment, in reading order. Kind or flag reason on the
// left, everything the pipeline connected it to on the right. Batch positions
// (`batch_index`) are accepted-only; fragment positions cover flags too.

function rrPct(x) { return typeof x === 'number' ? x.toFixed(2) : ''; }

function rrConnections(res, draft) {
  // batch_index -> [{ kind, label }] ; kind ∈ text|rule|merge|conflict|cue
  const by = {};
  const add = (i, c) => { (by[i] = by[i] || []).push(c); };
  const posOf = (bi) => `#${bi}`;
  // Input-derived links from the batch op (@N refs = accepted positions).
  const batchOp = draft && (draft.ops || []).find(o => o.kind === 'upsert_statements');
  const stmts = (batchOp && batchOp.payload && batchOp.payload.statements) || [];
  stmts.forEach((st, i) => (st.links || []).forEach(l => {
    const t = typeof l.to_id === 'string' && l.to_id.startsWith('@') ? posOf(l.to_id.slice(1)) : (l.to_id || '');
    add(i, { kind: 'text', label: `${l.link_type} → ${t}` });
  }));
  (res.links || []).forEach(l => {
    // source/target are edge refs; render both symmetrically so the label
    // stays honest even for an edge that doesn't touch this statement.
    const name = (ref) => ref === `@${l.batch_index}` ? 'this'
      : (typeof ref === 'string' && ref.startsWith('@') ? posOf(ref.slice(1)) : 'existing');
    const label = `${name(l.source)} ${l.link_type} → ${name(l.target)}`;
    add(l.batch_index, { kind: 'rule', label, note: `${l.pattern} · "${l.cue}" · ${rrPct(l.score)}` });
  });
  (res.merges || []).forEach(m => add(m.batch_index, { kind: 'merge', label: 'merge → existing', note: `"${(m.into_text || '').slice(0, 60)}" · ${rrPct(m.score)}${m.nli ? ' · NLI ↔' : ''}` }));
  (res.conflicts || []).forEach(c => add(c.batch_index, { kind: 'conflict', label: 'conflict ↔ existing', note: `"${(c.text || '').slice(0, 60)}" · NLI ${rrPct(c.nli && c.nli.forward && c.nli.forward.confidence)}` }));
  return by;
}

function RulesResult({ res, draft, onOpen, onAgain }) {
  const frags = res.fragments || { total: 0, resolved: 0, flagged: 0 };
  const props = res.proposals || {};
  const cues = res.cues || {};
  const conn = rrConnections(res, draft);
  const byFrag = {};
  (res.items || []).forEach(it => { byFrag[it.fragment_index] = { item: it, notes: [] }; });
  // A cue flag annotates a connective next to an accepted fragment; it must not
  // replace that fragment's row. Only fragment-level flags become rows.
  (res.flags || []).forEach(f => {
    const cur = byFrag[f.fragment_index];
    if (f.reason === 'cue' || (cur && cur.item)) { if (cur) cur.notes.push(f); else byFrag[f.fragment_index] = { flag: f, notes: [] }; }
    else byFrag[f.fragment_index] = { flag: f, notes: [] };
  });
  const rows = Object.keys(byFrag).map(Number).sort((a, b) => a - b).map(fi => ({ fi, ...byFrag[fi] }));
  const textLinks = Object.values(conn).flat().filter(c => c.kind === 'text').length;
  const cueTotal = (cues.auto || 0) + (cues.low_confidence || 0) + (cues.unresolved || 0) + (cues.direction_conflict || 0) + (cues.negated || 0) + (cues.strict || 0);
  const noDraft = !res.draft_id;
  return (
    <div className="rr">
      <div className="rr-stats">
        <div><span className="k">fragments</span><span className="v">{frags.total}</span></div>
        <div><span className="k">statements</span><span className="v">{frags.resolved}</span></div>
        <div><span className="k">flagged</span><span className={`v${frags.flagged ? ' warn' : ''}`}>{frags.flagged}</span></div>
        <div><span className="k">links</span><span className="v">{textLinks + (props.links || 0)}<small>{textLinks} text · {props.links || 0} rule</small></span></div>
        <div><span className="k">merges · conflicts</span><span className="v">{props.merges || 0} · {props.conflicts || 0}<small>{res.suppressed_negations ? `${res.suppressed_negations} negated ` : ''}{res.suppressed_conflicts ? `${res.suppressed_conflicts} suppressed` : ''}</small></span></div>
        <div><span className="k">unknown cues</span><span className="v">{cueTotal}<small>{cues.auto ? `${cues.auto} auto ` : ''}{cues.low_confidence ? `${cues.low_confidence} low-conf ` : ''}{cues.unresolved ? `${cues.unresolved} flagged ` : ''}{cues.direction_conflict ? `${cues.direction_conflict} direction ` : ''}{cues.negated ? `${cues.negated} negated` : ''}</small></span></div>
      </div>
      {noDraft ? <EmptyState title="Nothing to draft" blurb="No fragment resolved into a statement and nothing was flagged — the text produced no draft." /> : (
        <table className="rr-table">
          <thead><tr><th>#</th><th>kind</th><th>fragment</th><th>connections</th></tr></thead>
          <tbody>
            {rows.map(r => {
              const it = r.item, fl = r.flag;
              const bi = it ? it.batch_index : null;
              const cs = it ? (conn[bi] || []) : [];
              return (
                <tr key={r.fi} className={fl ? 'flagged' : ''}>
                  <td className="n">{it ? `#${bi}` : `f${r.fi}`}</td>
                  <td>{it ? <span className="rr-kind">{it.kind}</span> : <span className="rr-kind is-flag">flag · {fl.reason}</span>}</td>
                  <td className="t">{(it || fl).text}{it && it.note ? <div className="rr-note">{it.note}</div> : null}</td>
                  <td className="c">
                    {fl ? <span className="rr-why">{fl.reason === 'unmatched' ? 'no phrasing shape matched' : fl.reason === 'ambiguous' ? 'several kinds matched' : fl.reason === 'unsplit' ? 'compound remnant the segmenter could not split' : fl.reason}</span> : null}
                    {cs.map((c, i) => <div key={i} className={`rr-link ${c.kind}`}><b>{c.label}</b>{c.note ? <span className="rr-note"> {c.note}</span> : null}</div>)}
                    {(r.notes || []).map((f, i) => <div key={`n${i}`} className="rr-why">unknown connective after this fragment — see connectives below</div>)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {(res.cue_resolutions || []).length ? (
        <div className="rr-cues">
          <span className="k">unknown connectives</span>
          {(res.cue_resolutions || []).map((c, i) => (
            <span key={i} className={`rr-cue ${c.decision}`}>"{c.cue}" → {c.link_type || 'no type'} · {c.decision}{typeof c.score === 'number' ? ` · ${rrPct(c.score)}` : ''}</span>
          ))}
        </div>
      ) : null}
      <div className="rr-foot">
        <span className="if-meta">
          {res.draft_id ? <>draft <b>{res.draft_id}</b> · {res.draft && res.draft.status} · {res.draft && res.draft.op_count} ops{res.draft && res.draft.flags ? ` (${res.draft.flags} flags` : ''}{res.draft && res.draft.aliases ? `${res.draft.flags ? ', ' : ' ('}${res.draft.aliases} alias absorption)` : (res.draft && res.draft.flags ? ')' : '')}</> : 'no draft created'}
          {res.nli === 'unavailable' ? <span className="rr-warn"> · NLI unavailable — merges are similarity-only</span> : null}
        </span>
        <span className="if-spacer" />
        <button className="btn" onClick={onAgain}>Back to text</button>
        {res.draft_id ? <button className="btn extract" onClick={onOpen}>Open draft →</button> : null}
      </div>
    </div>
  );
}

Object.assign(window, { IngestSurface });
