// find.jsx — live Find: semantic / grep / survey via Myc.find. Surfaces real scores; never hides the tail.
const { useState: useStateF, useEffect: useEffectF } = React;

// Lane metadata — presentational only. The actual search runs server-side via
// Myc.find(mode, query); these carry the lane name/icon/desc and the note copy.
const MODES = {
  semantic: { name: 'Semantic', icon: 'semantic', desc: 'meaning · fuzzy',
    note: <>Vector search over embeddings — ranked by <b>meaning</b>, not wording. Recall-oriented; near-misses are expected.</> },
  grep: { name: 'Grep', icon: 'grep', desc: 'literal · alias-aware',
    note: <>Literal substring match, <b>alias-aware</b>: a hit on any Name routes through to the statements that mention it.</> },
  survey: { name: 'Survey', icon: 'survey', desc: 'breadth · no floor',
    note: <>Splits your query into sub-queries and merges results. <b>No score floor</b> — the long tail rides along; you judge it.</> },
};

function FindLanes({ mode, query, onMode }) {
  return (
    <div className="find-lanes">
      <span className="ll">mode</span>
      {Object.entries(MODES).map(([k, m]) => {
        const Icon = I[m.icon];
        return (
          <button key={k} className={`lane${mode === k ? ' on' : ''}`} onClick={() => onMode(k)}>
            <Icon className="lane-glyph" />
            <span className="lane-name">{m.name}</span>
            <span className="lane-desc">{m.desc}</span>
          </button>
        );
      })}
    </div>
  );
}

function ResultRow({ r, rank, mode, query, tail }) {
  const router = useRouter();
  const s = r.statement;
  const isGrep = mode === 'grep';
  return (
    <div className={`res${tail ? ' tail' : ''}`} onClick={() => router.go({ view: 'statement', id: s.id })}>
      <div className="r-rank">{String(rank).padStart(2, '0')}</div>
      <div className="r-kind"><KindTag kind={s.kind} /></div>
      <div className="r-body">
        <div className="r-id">{s.id}{isGrep && (r.via === 'mention' || r.via === 'both') ? <> · via alias</> : null}{isGrep && r.occ ? <> · {r.occ}×</> : null}</div>
        <EditableStatementText statement={s} idx={window.MYCELIUM_INDEX} className="r-text" highlightQuery={isGrep ? query : ''} compact />
      </div>
      <div className="r-right">
        {/* grep is deterministic — no relevance score. Show the real signal:
            matched_via + occurrence count, not a fabricated meter. */}
        {isGrep ? (
          <span className="r-sub" title={`matched via ${r.via || 'text'}`}>
            {r.via || 'text'}{r.occ > 0 ? <> · {r.occ}×</> : null}
          </span>
        ) : (
          <ScoreMeter score={r.score} />
        )}
      </div>
    </div>
  );
}

function FindResults({ query, mode }) {
  const router = useRouter();
  const m = MODES[mode] || MODES.semantic;
  const [state, setState] = useStateF({ loading: false, rows: [], error: null });

  useEffectF(() => {
    const q = (query || '').trim();
    if (!q) { setState({ loading: false, rows: [], error: null }); return; }
    let live = true;
    setState({ loading: true, rows: [], error: null });
    window.Myc.find(mode, q)
      .then((res) => { if (live) setState({ loading: false, rows: (res && res.rows) || [], error: null }); })
      .catch((err) => { if (live) setState({ loading: false, rows: [], error: err }); });
    return () => { live = false; };
  }, [query, mode]);

  if (!query || !query.trim()) {
    return <main className="page narrow"><EmptyState title="Nothing to find yet" blurb="Type a query and pick a mode. Find returns raw matches with scores — you judge relevance." /></main>;
  }

  const { loading, rows, error } = state;

  // survey: split strong head from faded tail
  let head = rows, tail = [];
  if (mode === 'survey') {
    head = rows.filter(r => r.score >= 0.4);
    tail = rows.filter(r => r.score < 0.4);
  }

  return (
    <main className="page narrow">
      <div className="crumbs">
        <a onClick={() => router.go({ view: 'landing' })}>~</a><span className="sep">/</span>
        <span>find</span><span className="sep">/</span><span className="here">{query}</span>
      </div>

      <div className="find-head">
        <h1>find <span className="q">{query}</span></h1>
        <span className="fh-mode">{m.name.toLowerCase()}</span>
        <span className="fh-count">{loading ? 'searching…' : `${rows.length} result${rows.length === 1 ? '' : 's'}`}</span>
      </div>

      <FindLanes mode={mode} query={query} onMode={(k) => router.go({ view: 'find', query, mode: k })} />

      <div className="find-note"><I.find className="fn-icon" width="15" height="15" /><div>{m.note}</div></div>

      {loading ? (
        <div className="results reveal">
          <div className="res">
            <div className="r-rank">··</div>
            <div className="r-body"><div className="r-text">searching…</div></div>
          </div>
        </div>
      ) : error ? (
        <div style={{ marginTop: 24 }}>
          <EmptyState
            title={error.status === 401 || error.status === 403 ? 'Sign in to search' : 'Find failed'}
            blurb={error.message || 'The substrate did not answer. Try again.'}
          />
        </div>
      ) : rows.length === 0 ? (
        <div style={{ marginTop: 24 }}>
          <EmptyState
            title={mode === 'grep' ? <>No literal match for “{query}”</> : <>No matches for “{query}”</>}
            blurb={mode === 'grep' ? 'Grep is exact. Try Semantic for meaning-based recall, or check the wording.' : 'An empty result is a signal, not a failure — the substrate may not cover this yet.'}
          />
        </div>
      ) : (
        <div className="results reveal">
          {head.map((r, i) => <ResultRow key={r.id} r={r} rank={i + 1} mode={mode} query={query} />)}
          {tail.length > 0 && (
            <>
              <div className="tail-divider">long tail · {tail.length} weak match{tail.length === 1 ? '' : 'es'} · shown, not hidden</div>
              {tail.map((r, i) => <ResultRow key={r.id} r={r} rank={head.length + i + 1} mode={mode} query={query} tail />)}
            </>
          )}
        </div>
      )}
    </main>
  );
}

Object.assign(window, { FindResults, MODES, FindLanes });
