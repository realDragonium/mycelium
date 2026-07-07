// Mycelium screens — dev-tool aesthetic. Landing, Search results, Statement detail, Entity detail, Browse.

const { useState: useStateS, useEffect: useEffectS, useMemo: useMemoS, useRef: useRefS } = React;

// ---------- Landing ----------

function Landing() {
  const router = useRouter();
  const data = window.MYCELIUM_DATA;
  const inputRef = useRefS(null);
  const [val, setVal] = useStateS('');

  useEffectS(() => { inputRef.current?.focus(); }, []);

  const submit = (e) => {
    e?.preventDefault();
    router.go({ view: 'search', query: val });
  };

  const recent = data.statements.slice(0, 8);
  const idx = window.MYCELIUM_INDEX;

  return (
    <main className="page landing">
      <section className="landing-hero">
        <div className="landing-pre">
          mycelium <b>v0.1</b> · read-only browser · {data.entities.length + data.statements.length + data.names.length} records · {data.links.length} links
        </div>
        <h1 className="landing-title">Browse the substrate.</h1>
        <p className="landing-blurb">
          Read-only inspection of entities, statements, names and the typed links between them.
          Search resolves across all three record kinds.
        </p>
      </section>

      <form className="big-search" onSubmit={submit}>
        <SearchIcon size={16} />
        <input
          ref={inputRef}
          type="text"
          value={val}
          onChange={e => setVal(e.target.value)}
          placeholder="Search records (entity name, statement text, alias)…"
          spellCheck={false}
        />
        <span className="kbd">⌘K</span>
      </form>

      <div className="big-search-hint">
        <span><b onClick={() => router.go({ view: 'search', query: 'reranker' })}>reranker</b></span>
        <span><b onClick={() => router.go({ view: 'search', query: 'mention' })}>mention</b></span>
        <span><b onClick={() => router.go({ view: 'search', query: 'HNSW' })}>HNSW</b></span>
        <span><b onClick={() => router.go({ view: 'search', query: 'pipeline' })}>pipeline</b></span>
        <span><b onClick={() => router.go({ view: 'search', query: 'graph' })}>graph</b></span>
      </div>

      <div className="landing-stats">
        <div className="stat"><div className="stat-l">entities</div><div className="stat-n">{data.entities.length}</div></div>
        <div className="stat"><div className="stat-l">statements</div><div className="stat-n">{data.statements.length}</div></div>
        <div className="stat"><div className="stat-l">names</div><div className="stat-n">{data.names.length}</div></div>
        <div className="stat"><div className="stat-l">links</div><div className="stat-n">{data.links.length}</div></div>
      </div>

      <section className="landing-recent">
        <header className="section-head">
          <h2>statements</h2>
          <span className="meta">no root · {data.statements.length} rows</span>
        </header>
        <table className="tbl">
          <thead>
            <tr>
              <th style={{width:'1%'}}>#</th>
              <th style={{width:'1%'}}>kind</th>
              <th style={{width:'1%'}}>id</th>
              <th>title</th>
              <th style={{width:'1%', textAlign:'right'}}>out</th>
              <th style={{width:'1%', textAlign:'right'}}>in</th>
              <th style={{width:'1%', textAlign:'right'}}>mentions</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((b, i) => (
              <tr key={b.id} onClick={() => router.go({ view: 'statement', id: b.id })}>
                <td className="col-num">{String(i+1).padStart(2,'0')}</td>
                <td><ClaimKindTag kind={b.kind} /></td>
                <td className="col-id"><span className="row-id">{b.id}</span></td>
                <td className="col-title"><b>{b.title}</b></td>
                <td className="col-meta">{(idx.outgoing[b.id]||[]).length}</td>
                <td className="col-meta">{(idx.incoming[b.id]||[]).length}</td>
                <td className="col-meta">{(b.mentions||[]).length}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{marginTop:8}}>
          <button
            onClick={() => router.go({view:'browse'})}
            style={{fontFamily:'var(--mono)', fontSize:11, color:'var(--accent)', padding:'4px 0'}}
          >show all {data.statements.length} →</button>
        </div>
      </section>
    </main>
  );
}

// ---------- Search results ----------

function SearchResults({ query }) {
  const router = useRouter();
  const data = window.MYCELIUM_DATA;
  const idx = window.MYCELIUM_INDEX;
  const [filter, setFilter] = useStateS('all');

  const all = useMemoS(() => searchAll(data, query), [data, query]);

  if (!query || !query.trim()) {
    return <main className="page narrow"><EmptyState
      title="No query"
      blurb="Searches across entities, statements and names. Names route to the entity they alias."
    /></main>;
  }
  if (all.length === 0) {
    return <main className="page narrow"><EmptyState
      title={<>0 matches for <code style={{fontFamily:'var(--mono)'}}>“{query}”</code></>}
      blurb="Try a broader term, or jump to one of these:"
      suggestions={data.entities.slice(0, 6).map(e => ({ id: e.id, label: e.name }))}
      onSuggest={(id) => router.go({ view: 'entity', id })}
    /></main>;
  }

  const counts = { all: all.length, entity: 0, statement: 0, name: 0, annotation: 0 };
  all.forEach(r => { counts[r.kind]++; });
  const filtered = filter === 'all' ? all : all.filter(r => r.kind === filter);

  return (
    <main className="page narrow">
      <div className="crumbs">
        <a href="#" onClick={(e) => { e.preventDefault(); router.go({ view: 'landing' }); }}>~</a>
        <span className="sep">/</span>
        <span>search</span>
        <span className="sep">/</span>
        <span className="id">{query}</span>
      </div>
      <header className="results-head" style={{marginTop:8}}>
        <h1>
          <b>{query}</b>
          <span className="qct">{all.length} match{all.length===1?'':'es'}</span>
        </h1>
        <div className="results-tabs">
          {['all', 'entity', 'statement', 'annotation', 'name'].map(k => (
            <button key={k} className={filter === k ? 'is-active' : ''} onClick={() => setFilter(k)}>
              {k}<span className="ct">{counts[k]}</span>
            </button>
          ))}
        </div>
      </header>

      <div>
        {filtered.map((r, i) => <ResultRow key={r.kind + ':' + r.record.id} result={r} query={query} idx={i+1} />)}
      </div>
    </main>
  );
}

function ResultRow({ result, query, idx: rowIdx }) {
  const router = useRouter();
  const data = window.MYCELIUM_DATA;
  const r = result.record;
  if (result.kind === 'entity') {
    const aliasCount = data.names.filter(n => n.entity === r.id).length;
    const mentionCount = data.statements.filter(b => (b.mentions || []).includes(r.id)).length;
    return (
      <div className="result-row" onClick={() => router.go({ view: 'entity', id: r.id })}>
        <span className="res-num">{String(rowIdx).padStart(2,'0')}</span>
        <KindTag kind="entity" />
        <span className="res-id">{r.id}</span>
        <span className="res-title">{highlight(r.name, query)}</span>
        <span className="res-snippet">{highlight(r.description, query)}</span>
        <span className="res-meta">{aliasCount}n · {mentionCount}↙</span>
      </div>
    );
  }
  if (result.kind === 'statement') {
    return (
      <div className="result-row" onClick={() => router.go({ view: 'statement', id: r.id })}>
        <span className="res-num">{String(rowIdx).padStart(2,'0')}</span>
        <KindTag kind="statement" />
        <ClaimKindTag kind={r.kind} />
        <span className="res-id">{r.id}</span>
        <span className="res-title">{highlight(r.title, query)}</span>
        <span className="res-snippet">{highlight(r.text, query)}</span>
        <span className="res-meta">{(window.MYCELIUM_INDEX.outgoing[r.id]||[]).length}↗ {(window.MYCELIUM_INDEX.incoming[r.id]||[]).length}↙</span>
      </div>
    );
  }
  if (result.kind === 'annotation') {
    // Click navigates to the first statement or entity it's attached to,
    // since annotations don't have their own detail page yet.
    const target = (r.statements || [])[0]
      ? { view: 'statement', id: r.statements[0] }
      : (r.entities || [])[0]
      ? { view: 'entity', id: r.entities[0] }
      : null;
    const attachCount = (r.statements || []).length + (r.entities || []).length;
    return (
      <div className="result-row" onClick={() => target && router.go(target)} style={!target ? {opacity:0.6} : null}>
        <span className="res-num">{String(rowIdx).padStart(2,'0')}</span>
        <KindTag kind="annotation" />
        <span className="res-id">{r.id}</span>
        <span className="res-title">{highlight(r.kind, query)}</span>
        <span className="res-snippet">{highlight(r.text, query)}</span>
        <span className="res-meta">{attachCount > 0 ? `→ ${attachCount}` : 'orphan'}</span>
      </div>
    );
  }
  const ent = data.entities.find(e => e.id === r.entity);
  return (
    <div className="result-row" onClick={() => router.go({ view: 'entity', id: r.entity })}>
      <span className="res-num">{String(rowIdx).padStart(2,'0')}</span>
      <KindTag kind="name" />
      <span className="res-id">{r.id}</span>
      <span className="res-title"><em>“{highlight(r.text, query)}”</em></span>
      <span className="res-snippet" style={{fontFamily:'var(--mono)', fontSize:'var(--fs-xs)'}}>→ {ent?.id} · {ent?.name}</span>
      <span className="res-meta">alias</span>
    </div>
  );
}

// ---------- Detail nav (left rail) ----------

function DetailNav({ activeId, kind: activeKind }) {
  const router = useRouter();
  const data = window.MYCELIUM_DATA;
  const idx = window.MYCELIUM_INDEX;
  const [tab, setTab] = useStateS(activeKind === 'entity' ? 'entity' : 'statement');

  // singular -> dataset
  const SETS = { statement: data.statements, entity: data.entities, name: data.names };
  const PLURAL = { statement: 'statements', entity: 'entities', name: 'names' };
  const activeSet = SETS[tab] || [];

  return (
    <nav className="detail-nav">
      <div style={{display:'flex', padding:'6px 8px 0', gap:4}}>
        {['statement', 'entity', 'name'].map(k => (
          <button
            key={k}
            className={tab === k ? 'is-active' : ''}
            onClick={() => setTab(k)}
            style={{
              fontFamily:'var(--mono)', fontSize:10.5,
              padding:'3px 8px', borderRadius:3,
              color: tab === k ? 'var(--ink)' : 'var(--ink-3)',
              background: tab === k ? 'var(--bg-3)' : 'transparent',
            }}
          >
            {k}<span style={{marginLeft:6, color:'var(--ink-4)'}}>{SETS[k]?.length || 0}</span>
          </button>
        ))}
      </div>
      <div className="nav-section-title">{PLURAL[tab]} · {activeSet.length}</div>
      <div>
        {tab === 'statement' && data.statements.map(b => (
          <div
            key={b.id}
            className={`nav-row k-statement${activeId === b.id ? ' is-active' : ''}`}
            onClick={() => router.go({ view: 'statement', id: b.id })}
            title={b.title}
          >
            <span className="marker" />
            <span className="label" style={{fontFamily:'var(--mono)', fontSize:10.5, color:'var(--ink-3)'}}>
              {b.id.replace(/^b_/,'')}
            </span>
          </div>
        ))}
        {tab === 'entity' && data.entities.map(e => (
          <div
            key={e.id}
            className={`nav-row k-entity${activeId === e.id ? ' is-active' : ''}`}
            onClick={() => router.go({ view: 'entity', id: e.id })}
            title={e.name}
          >
            <span className="marker" />
            <span className="label">{e.name}</span>
          </div>
        ))}
        {tab === 'name' && data.names.map(n => {
          const ent = idx.byId[n.entity];
          return (
            <div
              key={n.id}
              className="nav-row k-name"
              onClick={() => router.go({ view: 'entity', id: n.entity })}
              title={`${n.text} → ${ent?.name}`}
            >
              <span className="marker" />
              <span className="label" style={{fontFamily:'var(--mono)', fontSize:10.5}}>
                {n.text} <span style={{color:'var(--ink-4)'}}>→ {ent?.name}</span>
              </span>
            </div>
          );
        })}
      </div>
    </nav>
  );
}

// ---------- Statement detail ----------

// Walk an incoming chain along a single typed link (default 'contains').
// Returns ancestor list ordered root → … → immediate predecessor (excludes self). Cycle-safe.
function computeLineage(id, idx, maxDepth = 6, type = 'contains') {
  const out = [];
  const seen = new Set([id]);
  let cur = id;
  for (let i = 0; i < maxDepth; i++) {
    const incoming = idx.incoming[cur] || [];
    const matches = incoming.filter(l => l.link_type === type);
    if (!matches.length) break;
    const next = matches[0].from;
    if (seen.has(next)) break;
    seen.add(next);
    out.unshift(idx.byId[next]);
    cur = next;
  }
  return out;
}

function StatementDetail({ id }) {
  const router = useRouter();
  const idx = window.MYCELIUM_INDEX;
  const b = idx.byId[id];
  const [connMode, setConnMode] = useStateS('graph');

  // hooks must be unconditional
  const allOutgoing = (idx.outgoing[id] || []).filter(l => idx.byId[l.to] && idx.byId[l.to].kind === 'statement');
  const allIncoming = (idx.incoming[id] || []).filter(l => idx.byId[l.from] && idx.byId[l.from].kind === 'statement');

  // collect distinct types present on this statement, in stable order
  const typeCounts = {};
  [...allOutgoing, ...allIncoming].forEach(l => { typeCounts[l.link_type] = (typeCounts[l.link_type] || 0) + 1; });
  const presentTypes = Object.keys(typeCounts).sort((a, c) => {
    if (a === 'contains') return -1;
    if (c === 'contains') return 1;
    return typeCounts[c] - typeCounts[a] || a.localeCompare(c);
  });

  // primary type — the structural anchor. defaults to 'contains' if present, else the first available.
  const primaryType = presentTypes.includes('contains') ? 'contains' : (presentTypes[0] || 'contains');

  // active filter — which types to show. Defaults to ALL present types
  // so a reader sees the full neighborhood without first having to
  // discover the chip row. The primary type still gets visual emphasis
  // (thicker edges, solid borders) — the chip filter is for trimming
  // the view, not for revealing it.
  const [activeTypes, setActiveTypes] = React.useState(() => new Set(presentTypes));

  // reset filter when navigating to a different statement
  React.useEffect(() => {
    setActiveTypes(new Set(presentTypes));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (!b || b.kind !== 'statement') return <NotFoundState what="statement" />;

  const mentioned = (b.mentions || []).map(eid => idx.byId[eid]).filter(Boolean);

  // build active edge sets (filtered by activeTypes), each annotated with target node
  const outgoing = allOutgoing
    .filter(l => activeTypes.has(l.link_type))
    .map(l => ({ link: l, target: idx.byId[l.to], link_type: l.link_type, isPrimary: l.link_type === primaryType }));
  const incoming = allIncoming
    .filter(l => activeTypes.has(l.link_type))
    .map(l => ({ link: l, target: idx.byId[l.from], link_type: l.link_type, isPrimary: l.link_type === primaryType }));

  // sort: primary first, then by type, then by target title
  const sortConn = (arr) => arr.slice().sort((x, y) => {
    if (x.isPrimary !== y.isPrimary) return x.isPrimary ? -1 : 1;
    if (x.link_type !== y.link_type) return x.link_type.localeCompare(y.link_type);
    return (x.target.title || x.target.text || '').localeCompare(y.target.title || y.target.text || '');
  });
  const outSorted = sortConn(outgoing);
  const inSorted  = sortConn(incoming);

  // lineage walks the primary type chain (incoming side — "this is a part of …")
  const lineage = computeLineage(id, idx, 6, primaryType);

  const toggleType = (t) => {
    setActiveTypes(prev => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  };
  const setOnly = (t) => setActiveTypes(new Set([t]));
  const setAll  = () => setActiveTypes(new Set(presentTypes));

  return (
    <main className="page narrow">
      <div className="crumbs">
        <a href="#" onClick={(e) => { e.preventDefault(); router.go({ view: 'landing' }); }}>~</a>
        <span className="sep">/</span>
        <a href="#" onClick={(e) => { e.preventDefault(); router.go({ view: 'browse' }); }}>statements</a>
        <span className="sep">/</span>
        <span className="id">{b.id}</span>
      </div>

      {/* dense top bar */}
      <section className="i-bar">
        <div className="id-block">
          <div className="kind-square">B</div>
          <div className="id-stack">
            <span className="kind-label">
              statement
              {b.claimKind && <ClaimKindTag kind={b.claimKind} />}
            </span>
            <span className="id">{b.id}</span>
          </div>
        </div>

        <div className="stats">
          <div className="stat-cell"><span className="n">{allIncoming.length}</span><span className="lbl">↑ incoming</span></div>
          <div className="stat-cell acc"><span className="n">{allOutgoing.length}</span><span className="lbl">↓ outgoing</span></div>
          <div className="stat-cell"><span className="n">{presentTypes.length}</span><span className="lbl">⌗ link types</span></div>
          <div className="stat-cell"><span className="n">{mentioned.length}</span><span className="lbl">◆ entities</span></div>
          {(idx.conditionUses[b.id] || []).length > 0 && (
            <div className="stat-cell"><span className="n">{idx.conditionUses[b.id].length}</span><span className="lbl">⚡ conditions</span></div>
          )}
        </div>

        <div className="thumb" title="local neighborhood">
          <ThumbGraph parents={allIncoming.length} children={allOutgoing.length} />
        </div>

        <div className="ops">
          <button className="op" onClick={() => navigator.clipboard?.writeText(b.id)}>⎘ copy id</button>
          <button className="op primary" onClick={() => router.go({ view: 'graph', focus: b.id })}>view in graph</button>
        </div>
      </section>

      {/* body pane */}
      <section className="i-body">
        <div className="corner">REC <b>{String(b.recordIdx ?? Math.abs(hashCode(b.id) % 9999)).padStart(4,'0')}</b> · LAST INDEXED 2025-04-12</div>
        <h1 className="bv-title">statement.text</h1>
        <StatementText statement={b} byId={idx.byId} className="text" />

        {lineage.length > 0 && (
          <div className="lineage-bar">
            <span className="lbl"><span className={`linktype-tag lt-${primaryType}`} style={{marginRight:6}}>{primaryType}</span>chain</span>
            {lineage.map((p) => (
              <React.Fragment key={p.id}>
                <span className="step" onClick={() => router.go({ view: 'statement', id: p.id })} title={p.title}>
                  {p.id.replace(/^b_/, '')}
                </span>
                <span className="arr">›</span>
              </React.Fragment>
            ))}
            <span className="here">{b.id.replace(/^b_/, '')}</span>
          </div>
        )}

        {mentioned.length > 0 && (
          <div className="ment-block-i">
            <span className="lbl">◆ {mentioned.length} related entities</span>
            <div className="ment-list">
              {mentioned.map(e => <EntityChip key={e.id} entity={e} />)}
            </div>
          </div>
        )}

        <AnnotationList
          title="annotations"
          sub="// typed propositions attached to this statement"
          annotations={idx.annotationsByStatement[id] || []}
          self={{ kind: 'statement', id }}
          style={{marginTop:18}}
        />
      </section>

      {/* connections panel — unified, type-filtered */}
      <section className="i-conn">
        <header className="i-conn-head">
          <span className="label">Connections</span>
          <span className="sub">// statement↔statement · primary type drawn strongest · <svg width="14" height="14" style={{verticalAlign:'middle'}}><circle cx="7" cy="7" r="5" fill="#d97706"/></svg> conditional · <svg width="14" height="14" style={{verticalAlign:'middle'}}><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.4"/></svg> no condition</span>
          <div className="toggle">
            <span className={`opt${connMode === 'graph' ? ' active' : ''}`} onClick={() => setConnMode('graph')}>graph</span>
            <span className={`opt${connMode === 'list' ? ' active' : ''}`} onClick={() => setConnMode('list')}>list</span>
          </div>
        </header>

        {/* type filter chips */}
        <div className="conn-filter">
          <span className="filter-lbl">types</span>
          {presentTypes.map(t => {
            const on = activeTypes.has(t);
            const isPrim = t === primaryType;
            return (
              <button
                key={t}
                className={`type-chip lt-${t}${on ? ' on' : ''}${isPrim ? ' primary' : ''}`}
                onClick={(e) => { if (e.shiftKey) toggleType(t); else if (on && activeTypes.size === 1) toggleType(t); else setOnly(t); }}
                onContextMenu={(e) => { e.preventDefault(); toggleType(t); }}
                title={`click: only ${t} · shift+click or right-click: toggle`}
              >
                {isPrim && <span className="prim-dot">▣</span>}
                <span className="t-name">{t}</span>
                <span className="t-ct">{typeCounts[t]}</span>
              </button>
            );
          })}
          {presentTypes.length > 1 && (
            <button className={`type-chip all${activeTypes.size === presentTypes.length ? ' on' : ''}`} onClick={setAll}>
              <span className="t-name">all</span>
            </button>
          )}
          <span className="filter-hint">click: only · shift-click: toggle</span>
        </div>

        {connMode === 'graph'
          ? <ConnectionsGraph incoming={inSorted} outgoing={outSorted} center={b} primaryType={primaryType} idx={idx} />
          : <ConnectionsList incoming={inSorted} outgoing={outSorted} primaryType={primaryType} idx={idx} />
        }

        {(allOutgoing.length + allIncoming.length) === 0 && (
          <div style={{padding:'24px 14px', fontFamily:'var(--mono)', fontSize:11.5, color:'var(--ink-4)'}}>
            // no statement connections — this node stands alone
          </div>
        )}

        {(idx.conditionUses[b.id] || []).length > 0 && (
          <div className="i-conditions" style={{marginTop: 28, padding: '14px 16px', borderTop: '1px solid var(--rule-soft)'}}>
            <h3 style={{fontFamily:'var(--mono)', fontSize:11.5, color:'var(--ink-4)', textTransform:'uppercase', letterSpacing:'0.08em', margin:'0 0 8px'}}>
              ⚡ Used as condition on {idx.conditionUses[b.id].length} edge{idx.conditionUses[b.id].length === 1 ? '' : 's'}
            </h3>
            <p style={{fontSize:12.5, color:'var(--ink-5)', margin:'0 0 12px', lineHeight:1.45}}>
              This statement gates the following edges via a <code>when</code> clause. The edge only fires when this statement holds.
            </p>
            <ul style={{listStyle:'none', padding:0, margin:0, display:'flex', flexDirection:'column', gap:6}}>
              {idx.conditionUses[b.id].map((l, i) => {
                const from = idx.byId[l.from];
                const to = idx.byId[l.to];
                const fromTxt = (from && (from.title || from.text)) || l.from;
                const toTxt = (to && (to.title || to.text)) || l.to;
                return (
                  <li
                    key={'cu' + i}
                    style={{
                      fontFamily:'var(--mono)', fontSize:12, lineHeight:1.45,
                      padding:'8px 10px', border:'1px solid var(--rule-soft)', borderRadius:4,
                      cursor:'pointer', color:'var(--ink-3)',
                    }}
                    onClick={() => router.go({ view: 'statement', id: l.from })}
                    title="open the from-side statement"
                  >
                    <span style={{color:'var(--ink-4)'}}>{fromTxt}</span>
                    <span style={{color:'var(--ink-6)', margin:'0 8px'}}>─[{l.link_type}]→</span>
                    <span style={{color:'var(--ink-3)'}}>{toTxt}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </section>
    </main>
  );
}

// thumbnail mini-graph for the top bar
function ThumbGraph({ parents, children }) {
  return (
    <svg viewBox="0 0 92 28" style={{width:'100%', height:'100%'}}>
      {parents > 0 && <line x1="14" y1="14" x2="46" y2="14" stroke="var(--ink-5)" strokeWidth="0.6" />}
      {children > 0 && <line x1="46" y1="14" x2="78" y2="6" stroke="var(--accent)" strokeWidth="0.6" opacity="0.7" />}
      {children > 1 && <line x1="46" y1="14" x2="78" y2="22" stroke="var(--accent)" strokeWidth="0.6" opacity="0.7" />}
      {parents > 0 && <circle cx="14" cy="14" r="2.4" fill="var(--ink-5)" />}
      <circle cx="46" cy="14" r="3.4" fill="var(--accent)" />
      {children > 0 && <circle cx="78" cy="6" r="2" fill="var(--accent)" opacity="0.8" />}
      {children > 1 && <circle cx="78" cy="22" r="2" fill="var(--accent)" opacity="0.8" />}
    </svg>
  );
}

// the showpiece: incoming flows in from the left, outgoing out to the right.
// edges are colored by link type and labeled. primary type drawn strongest.
function ConnNode({ entry, side, style }) {
  const router = useRouter();
  const [peek, setPeek] = React.useState(false);
  const t = entry.target;
  const isPrim = entry.isPrimary;
  const cls = `node ${side}${isPrim ? ' primary' : ' secondary'}${peek ? ' peeking' : ''}`;

  return (
    <div
      className={cls}
      style={style}
      onClick={() => router.go({ view: 'statement', id: t.id })}
    >
      <div className="nlabel">
        <span className={`linktype-tag lt-${entry.link_type}`} style={{marginBottom:4, display:'inline-block'}}>{entry.link_type}</span>
        <div>{t.title || t.text}</div>
        <span className="nid">{t.id}</span>
      </div>
      <button
        type="button"
        className="peek-btn"
        title="peek at full text"
        onClick={(e) => { e.stopPropagation(); setPeek(p => !p); }}
        onMouseEnter={() => setPeek(true)}
        onMouseLeave={() => setPeek(false)}
      >⌖</button>
      {peek && (
        <div className="peek-pop" onClick={(e) => e.stopPropagation()}>
          <div className="peek-head">
            <span className={`linktype-tag lt-${entry.link_type}`}>{entry.link_type}</span>
            <span className="peek-id">{t.id}</span>
            <span className="peek-hint">click card to open</span>
          </div>
          <div className="peek-body">{t.text}</div>
        </div>
      )}
    </div>
  );
}

// Render a when-clause tree as a human-readable string. Leaf shape is
// {statement_id}; composites are {op:'and'|'or', of:[...]}. Older substrate
// versions emitted a flat statement_id string, hence the typeof check.
function renderWhenTree(when, idx) {
  if (!when) return null;
  if (typeof when === 'string') {
    const w = idx && idx.byId ? idx.byId[when] : null;
    return (w && (w.title || w.text)) || when;
  }
  if (when.statement_id) {
    const w = idx && idx.byId ? idx.byId[when.statement_id] : null;
    return (w && (w.title || w.text)) || when.statement_id;
  }
  if (when.op && Array.isArray(when.of)) {
    const parts = when.of.map(child => renderWhenTree(child, idx));
    const sep = when.op === 'and' ? ' AND ' : ' OR ';
    return '(' + parts.join(sep) + ')';
  }
  return null;
}

// Returns the single leaf statement_id if `when` is a leaf (or legacy flat
// string), else null — used to gate click-to-navigate, since composite
// trees have no single target.
function whenLeafId(when) {
  if (!when) return null;
  if (typeof when === 'string') return when;
  if (when.statement_id && !when.op) return when.statement_id;
  return null;
}

// Edge-condition badge. Two variants so absence is as explicit as
// presence: amber "⚡ <when text>" when the edge has a condition, muted
// "· always" otherwise. A reader scanning the connections graph never
// has to guess "did I just miss a marker, or is this edge unconditional?"
// — every edge carries one of the two pills.
//
// The foreignObject gets a generous fixed bounding box (overflow:visible
// in CSS) and the inner pill sizes to its content as `inline-flex` —
// previously a tight estimated width clipped "always" to "alw…".
// Small geometric marker drawn on the edge midpoint to signal
// conditional vs unconditional at a glance. Both states get a marker so
// the question "is this conditioned?" is answerable from the geometry
// alone: amber filled bead = conditional (hover for the `when` text),
// hollow grey ring = unconditional. Both fit on the path itself, so
// they don't collide with node cards the way text labels did.
function ConditionMarker({ x, y, conditional, onEnter, onLeave }) {
  const hitR = 14;
  const handleEnter = (e) => onEnter && onEnter(e);
  const handleLeave = () => onLeave && onLeave();
  if (conditional) {
    return (
      <g className="cond-marker is-cond" onMouseEnter={handleEnter} onMouseLeave={handleLeave}>
        <circle cx={x} cy={y} r={hitR} fill="transparent" />
        <circle cx={x} cy={y} r="11" fill="#fde68a" opacity="0.55" />
        <circle cx={x} cy={y} r="6" fill="#d97706" stroke="var(--bg-2, #fff)" strokeWidth="1.6" />
      </g>
    );
  }
  return (
    <g className="cond-marker is-none" onMouseEnter={handleEnter} onMouseLeave={handleLeave}>
      <circle cx={x} cy={y} r={hitR} fill="transparent" />
      <circle cx={x} cy={y} r="6" fill="var(--bg-2, #fff)" stroke="currentColor" strokeWidth="1.4" opacity="0.7" />
    </g>
  );
}

// Renders a `when` tree as a vertical block of leaves and groups.
// Inline rendering with parens worked for short trees but degenerated
// at three+ leaves: an OR clause spread across two lines with a
// stranded ')' AND' tail. The block layout puts each composite in a
// labeled, bordered box (solid for AND, dashed for OR) with children
// stacked under it — structure reads at a glance without parens.
function WhenTreeJSX({ when, idx }) {
  if (!when) return null;
  const renderNode = (node, key) => {
    if (typeof node === 'string') {
      const w = idx?.byId?.[node];
      return <span key={key} className="leaf">{(w && (w.title || w.text)) || node}</span>;
    }
    if (node.statement_id && !node.op) {
      const w = idx?.byId?.[node.statement_id];
      return <span key={key} className="leaf">{(w && (w.title || w.text)) || node.statement_id}</span>;
    }
    if (node.op && Array.isArray(node.of)) {
      // Phrase the operator as a sentence so nested groups read on
       // their own line — "ALL OF · ANY OF" stacked indented was hard
       // to parse as two distinct levels.
      const opLabel = node.op === 'and'
        ? 'all of these must hold:'
        : 'at least one of these must hold:';
      return (
        <div key={key} className={`grp grp-${node.op}`}>
          <div className="op-label">{opLabel}</div>
          <div className="grp-children">
            {node.of.map((c, i) => <div key={i} className="grp-child">{renderNode(c, i)}</div>)}
          </div>
        </div>
      );
    }
    return null;
  };
  return <div className="tree-root">{renderNode(when, 'root')}</div>;
}

// Custom tooltip rendered in the i-conn-canvas (which is position:
// relative). Avoids the slow native <title> hover delay and lets us
// show structured content for conditional links — e.g. the AND/OR
// composition of the `when` tree.
function ConditionTooltip({ tip }) {
  if (!tip) return null;
  const { px, py, conditional, when, idx } = tip;
  return (
    <div
      className={`cond-tooltip${conditional ? ' is-cond' : ' is-none'}`}
      style={{ left: `${px}%`, top: `${py}%` }}
    >
      {conditional ? (
        <>
          <div className="head"><span className="bolt">⚡</span> conditional</div>
          <div className="sub">fires only when:</div>
          <div className="tree"><WhenTreeJSX when={when} idx={idx} /></div>
        </>
      ) : (
        <>
          <div className="head none">no condition</div>
          <div className="sub">this link always applies</div>
        </>
      )}
    </div>
  );
}

function ConnectionsGraph({ incoming, outgoing, center, primaryType, idx }) {
  const whenTextFor = (link) => {
    if (!link || !link.when) return null;
    const raw = renderWhenTree(link.when, idx);
    if (!raw) return null;
    return raw.length > 28 ? raw.slice(0, 27) + '…' : raw;
  };
  const router = useRouter();
  // Custom tooltip — native SVG <title> has a noticeable hover delay
  // and can't render structured content. We track marker hovers in
  // state and render an HTML overlay positioned over the canvas.
  const [tip, setTip] = useStateS(null);
  const onEnterCond = (e, link, x, y) => setTip({
    px: (x / W) * 100, py: (y / H) * 100,
    conditional: true, when: link.when, idx,
  });
  const onEnterNone = (e, x, y) => setTip({
    px: (x / W) * 100, py: (y / H) * 100,
    conditional: false, idx,
  });
  const onLeave = () => setTip(null);
  // Canvas grows with the busier side so each node gets a fixed-height
  // slot. Node card is ~80px tall (3-line clamp + padding); 96px gap
  // gives a little breathing room.
  const W = 1100;
  const NODE_STEP = 96;
  const TOP_PAD = 70;       // leaves room for the column labels
  const BOTTOM_PAD = 50;
  const MIN_H = 380;
  const maxSide = Math.max(incoming.length, outgoing.length, 1);
  const H = Math.max(MIN_H, TOP_PAD + BOTTOM_PAD + NODE_STEP * maxSide);
  const cx = W / 2, cy = H / 2;
  const inX = 200, outX = W - 200;

  const yFor = (i, n) => {
    if (n <= 1) return cy;
    // Each node owns NODE_STEP vertical pixels, column centered on cy.
    const totalSpan = NODE_STEP * (n - 1);
    const top = cy - totalSpan / 2;
    return top + NODE_STEP * i;
  };
  const pct = (x, y) => ({ left: `${(x / W) * 100}%`, top: `${(y / H) * 100}%` });

  return (
    <div className="i-conn-canvas" style={{height: H + 'px'}}>
      <svg className="edges" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <defs>
          <pattern id="conn-grid" x="0" y="0" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--rule-soft)" strokeWidth="1" />
          </pattern>
          <radialGradient id="conn-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.18" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </radialGradient>
        </defs>
        <rect width="100%" height="100%" fill="url(#conn-grid)" opacity="0.5" />
        <circle cx={cx} cy={cy} r="180" fill="url(#conn-glow)" />

        {incoming.map((p, i) => {
          const y = yFor(i, incoming.length);
          const isPrim = p.link_type === primaryType;
          const mid = (inX + cx) / 2;
          const cond = !!(p.link && p.link.when);
          return (
            <g key={'pe' + p.target.id + i} className={`edge lt-${p.link_type}${isPrim ? ' primary' : ''}${cond ? ' has-when' : ''}`}>
              <path
                d={`M ${inX + 100},${y} C ${mid},${y} ${mid},${cy} ${cx - 100},${cy}`}
                stroke="currentColor" strokeWidth={isPrim ? 1.6 : 0.9}
                fill="none" opacity={isPrim ? 0.95 : 0.55}
                strokeDasharray={isPrim ? '' : '3 3'}
              />
              <text
                x={mid + 6} y={(y + cy) / 2 - 14}
                fill="currentColor" fontFamily="var(--mono)" fontSize="9.5"
                opacity={isPrim ? 0.95 : 0.7}
                textAnchor="middle"
              >{p.link_type}</text>
              <ConditionMarker
                x={mid} y={(y + cy) / 2}
                conditional={cond}
                onEnter={(e) => cond
                  ? onEnterCond(e, p.link, mid, (y + cy) / 2)
                  : onEnterNone(e, mid, (y + cy) / 2)}
                onLeave={onLeave}
              />
            </g>
          );
        })}
        {outgoing.map((c, i) => {
          const y = yFor(i, outgoing.length);
          const isPrim = c.link_type === primaryType;
          const mid = (cx + outX) / 2;
          const cond = !!(c.link && c.link.when);
          return (
            <g key={'ce' + c.target.id + i} className={`edge lt-${c.link_type}${isPrim ? ' primary' : ''}${cond ? ' has-when' : ''}`}>
              <path
                d={`M ${cx + 100},${cy} C ${mid},${cy} ${mid},${y} ${outX - 100},${y}`}
                stroke="currentColor" strokeWidth={isPrim ? 1.6 : 0.9}
                fill="none" opacity={isPrim ? 0.9 : 0.55}
                strokeDasharray={isPrim ? '' : '3 3'}
              />
              <text
                x={mid - 6} y={(y + cy) / 2 - 14}
                fill="currentColor" fontFamily="var(--mono)" fontSize="9.5"
                opacity={isPrim ? 0.95 : 0.7}
                textAnchor="middle"
              >{c.link_type}</text>
              <ConditionMarker
                x={mid} y={(y + cy) / 2}
                conditional={cond}
                onEnter={(e) => cond
                  ? onEnterCond(e, c.link, mid, (y + cy) / 2)
                  : onEnterNone(e, mid, (y + cy) / 2)}
                onLeave={onLeave}
              />
            </g>
          );
        })}
      </svg>

      <ConditionTooltip tip={tip} />
      <span className="col-label" style={{left:`${(inX/W)*100}%`, transform:'translateX(-50%)'}}>↑ INCOMING · {incoming.length}</span>
      <span className="col-label" style={{left:'50%', transform:'translateX(-50%)', color:'var(--accent)'}}>▣ CURRENT</span>
      <span className="col-label" style={{left:`${(outX/W)*100}%`, transform:'translateX(-50%)', color:'var(--accent)'}}>↓ OUTGOING · {outgoing.length}</span>

      {incoming.length === 0 && (
        <div className="empty-side" style={pct(inX, cy)}>
          // no incoming<br/>under current filter
        </div>
      )}
      {incoming.map((p, i) => {
        const y = yFor(i, incoming.length);
        return (
          <ConnNode
            key={p.target.id + i}
            entry={p}
            side="parent"
            style={pct(inX, y)}
          />
        );
      })}

      <div className="node center" style={pct(cx, cy)}>
        <div className="nlabel">
          {center.title}
          <span className="nid">{center.id}</span>
        </div>
      </div>

      {outgoing.length === 0 && (
        <div className="empty-side" style={pct(outX, cy)}>
          // no outgoing<br/>under current filter
        </div>
      )}
      {outgoing.map((c, i) => {
        const y = yFor(i, outgoing.length);
        return (
          <ConnNode
            key={c.target.id + i}
            entry={c}
            side="child"
            style={pct(outX, y)}
          />
        );
      })}
    </div>
  );
}

// legacy alias kept while we transition (unused after this refactor)
function CompositionGraph({ parents, kids, center }) {
  const router = useRouter();
  const W = 1100, H = 360; // viewbox baseline
  const cx = W / 2, cy = H / 2;
  const parentX = 180, childX = W - 180;
  const spread = Math.max(parents.length, kids.length, 1);

  const yFor = (i, n) => {
    if (n <= 1) return cy;
    const span = Math.min(H - 100, 60 + n * 70);
    const top = cy - span / 2;
    return top + (span * i) / (n - 1);
  };

  // convert viewbox coords to percentage strings for absolute-positioned divs
  const pct = (x, y) => ({ left: `${(x / W) * 100}%`, top: `${(y / H) * 100}%` });

  return (
    <div className="i-conn-canvas" style={{height: H + 'px'}}>
      <svg className="edges" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <defs>
          <pattern id="conn-grid" x="0" y="0" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--rule-soft)" strokeWidth="1" />
          </pattern>
          <radialGradient id="conn-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.18" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </radialGradient>
        </defs>
        <rect width="100%" height="100%" fill="url(#conn-grid)" opacity="0.5" />
        <circle cx={cx} cy={cy} r="180" fill="url(#conn-glow)" />

        {parents.map((p, i) => {
          const y = yFor(i, parents.length);
          return (
            <path
              key={'pe' + p.target.id}
              d={`M ${parentX + 100},${y} C ${(parentX + cx) / 2},${y} ${(parentX + cx) / 2},${cy} ${cx - 100},${cy}`}
              stroke="var(--ink-5)" strokeWidth="1.4" fill="none"
            />
          );
        })}
        {kids.map((c, i) => {
          const y = yFor(i, kids.length);
          return (
            <path
              key={'ce' + c.target.id}
              d={`M ${cx + 100},${cy} C ${(cx + childX) / 2},${cy} ${(cx + childX) / 2},${y} ${childX - 100},${y}`}
              stroke="var(--accent)" strokeWidth="1.4" fill="none" opacity="0.65"
            />
          );
        })}
      </svg>

      <span className="col-label" style={{left:`${(parentX/W)*100}%`, transform:'translateX(-50%)'}}>↑ PARENTS · {parents.length}</span>
      <span className="col-label" style={{left:'50%', transform:'translateX(-50%)', color:'var(--accent)'}}>▣ CURRENT</span>
      <span className="col-label" style={{left:`${(childX/W)*100}%`, transform:'translateX(-50%)', color:'var(--accent)'}}>↓ CHILDREN · {kids.length}</span>

      {parents.length === 0 && (
        <div className="empty-side" style={pct(parentX, cy)}>
          // entry point<br/>no parents
        </div>
      )}
      {parents.map((p, i) => {
        const y = yFor(i, parents.length);
        return (
          <div
            key={p.target.id}
            className="node parent"
            style={pct(parentX, y)}
            onClick={() => router.go({ view: 'statement', id: p.target.id })}
          >
            <div className="nlabel">
              {p.target.title || p.target.text}
              <span className="nid">{p.target.id}</span>
              <div className="nmeta">
                <span>{(window.MYCELIUM_INDEX.incoming[p.target.id] || []).filter(l => l.link_type === 'contains').length}↑</span>
                <span>{(window.MYCELIUM_INDEX.outgoing[p.target.id] || []).filter(l => l.link_type === 'contains').length}↓</span>
              </div>
            </div>
          </div>
        );
      })}

      <div className="node center" style={pct(cx, cy)}>
        <div className="nlabel">
          {center.title}
          <span className="nid">{center.id}</span>
        </div>
      </div>

      {kids.length === 0 && (
        <div className="empty-side" style={pct(childX, cy)}>
          // leaf<br/>no sub-statements
        </div>
      )}
      {kids.map((c, i) => {
        const y = yFor(i, kids.length);
        return (
          <div
            key={c.target.id}
            className="node child"
            style={pct(childX, y)}
            onClick={() => router.go({ view: 'statement', id: c.target.id })}
          >
            <div className="nlabel">
              {c.target.title || c.target.text}
              <span className="nid">{c.target.id}</span>
              <div className="nmeta">
                <span>{(window.MYCELIUM_INDEX.incoming[c.target.id] || []).filter(l => l.link_type === 'contains').length}↑</span>
                <span>{(window.MYCELIUM_INDEX.outgoing[c.target.id] || []).filter(l => l.link_type === 'contains').length}↓</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ConnListItem({ entry, isPrim, idx }) {
  const router = useRouter();
  const [peek, setPeek] = React.useState(false);
  const t = entry.target;
  const when = entry.link && entry.link.when;
  const whenText = renderWhenTree(when, idx);
  // Navigation only makes sense for a single-leaf when; composite AND/OR
  // trees don't point at one statement.
  const navId = whenLeafId(when);
  const navTarget = navId && idx && idx.byId ? idx.byId[navId] : null;
  const hasWhen = !!when;
  return (
    <div
      className={`item${isPrim ? '' : ' secondary'}${peek ? ' peeking' : ''}${hasWhen ? ' has-when' : ''}`}
      onClick={() => router.go({ view: 'statement', id: t.id })}
    >
      <div className="item-row">
        <div className="item-body">
          <div style={{display:'flex', alignItems:'center', gap:6, flexWrap:'wrap'}}>
            {hasWhen
              ? <span className="when-badge" title="this edge fires only when its condition holds">⚡ conditional</span>
              : <span className="when-badge none" title="this edge has no `when` clause">no condition</span>}
            <span>{t.title || t.text}</span>
          </div>
          <span className="iid">{t.id}</span>
          {whenText && (
            <div
              className="when-line"
              style={{
                fontFamily: 'var(--mono)', fontSize: 10.5,
                marginTop: 4, cursor: navTarget ? 'pointer' : 'default',
              }}
              onClick={(e) => {
                e.stopPropagation();
                if (navTarget) router.go({ view: 'statement', id: navId });
              }}
            >
              ↳ when: {whenText}
            </div>
          )}
        </div>
        <button
          type="button"
          className="peek-btn flat"
          title="peek at full text"
          onClick={(e) => { e.stopPropagation(); setPeek(p => !p); }}
        >⌖</button>
      </div>
      {peek && (
        <div className="peek-inline" onClick={(e) => e.stopPropagation()}>
          {t.text}
        </div>
      )}
    </div>
  );
}

function ConnectionsList({ incoming, outgoing, primaryType, idx }) {

  // group entries by type, preserving the sort order (primary already first)
  const groupByType = (arr) => {
    const m = new Map();
    arr.forEach(x => { if (!m.has(x.link_type)) m.set(x.link_type, []); m.get(x.link_type).push(x); });
    return m;
  };
  const inGroups  = groupByType(incoming);
  const outGroups = groupByType(outgoing);

  const Section = ({ groups, dir }) => {
    const total = [...groups.values()].reduce((a, g) => a + g.length, 0);
    return (
      <div className={`col conn-col ${dir}`}>
        <h4>
          <span>{dir === 'in' ? '↑ incoming' : '↓ outgoing'}</span>
          <span className="ct">{total}</span>
        </h4>
        {total === 0 && (
          <div style={{fontFamily:'var(--mono)', fontSize:11, color:'var(--ink-4)'}}>// none under current filter</div>
        )}
        {[...groups.entries()].map(([type, items]) => {
          const isPrim = type === primaryType;
          return (
            <div key={type} className={`type-group${isPrim ? ' primary' : ''}`}>
              <div className="type-group-head">
                <span className={`linktype-tag lt-${type}`}>{type}</span>
                {isPrim && <span className="prim-flag">▣ primary</span>}
                <span className="ct">{items.length}</span>
              </div>
              {items.map((x, i) => (
                <ConnListItem key={x.target.id + i} entry={x} isPrim={isPrim} idx={idx} />
              ))}
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="i-conn-list">
      <Section groups={inGroups} dir="in" />
      <Section groups={outGroups} dir="out" />
    </div>
  );
}

// retained for any legacy callers — no longer used
function CompositionList({ parents, kids }) {
  const router = useRouter();
  return (
    <div className="i-conn-list">
      <div className="col">
        <h4>↑ parents <span className="ct">{parents.length}</span></h4>
        {parents.length === 0 && <div style={{fontFamily:'var(--mono)', fontSize:11, color:'var(--ink-4)'}}>// entry point — no parents</div>}
        {parents.map(p => (
          <div key={p.target.id} className="item" onClick={() => router.go({ view: 'statement', id: p.target.id })}>
            {p.target.title || p.target.text}
            <span className="iid">{p.target.id}</span>
          </div>
        ))}
      </div>
      <div className="col children">
        <h4>↓ children <span className="ct">{kids.length}</span></h4>
        {kids.length === 0 && <div style={{fontFamily:'var(--mono)', fontSize:11, color:'var(--ink-4)'}}>// leaf — no children</div>}
        {kids.map(c => (
          <div key={c.target.id} className="item" onClick={() => router.go({ view: 'statement', id: c.target.id })}>
            {c.target.title || c.target.text}
            <span className="iid">{c.target.id}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function OtherLinks({ otherOut, otherIn, idx }) {
  const router = useRouter();
  const groupBy = (arr) => { const m = {}; arr.forEach(x => { (m[x.link_type] = m[x.link_type] || []).push(x); }); return m; };
  const out = groupBy(otherOut);
  const inn = groupBy(otherIn);

  const Group = ({ type, items, dir }) => (
    <div style={{padding:'8px 14px', borderTop:'1px solid var(--rule-soft)'}}>
      <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:6}}>
        <span className={`linktype-tag lt-${type}`}>{type}</span>
        <span style={{fontFamily:'var(--mono)', fontSize:10, color:'var(--ink-4)'}}>
          {dir === 'out' ? '↗ outgoing' : '↙ incoming'}
        </span>
        <span style={{marginLeft:'auto', fontFamily:'var(--mono)', fontSize:10, color:'var(--ink-4)'}}>{items.length}</span>
      </div>
      <div style={{display:'flex', flexDirection:'column', gap:4}}>
        {items.map((l, i) => {
          const tid = dir === 'out' ? l.to : l.from;
          const t = idx.byId[tid];
          if (!t) return null;
          return (
            <div key={i} className={`linkrow lt-${type}`} onClick={() => router.go({ view: 'statement', id: tid })} style={{paddingLeft:24}}>
              <div className="body">
                {t.title || t.text}
                <small>{tid}</small>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );

  return (
    <section className="i-conn" style={{marginTop:0}}>
      <header className="i-conn-head">
        <span className="label" style={{}}>Other typed links</span>
        <span className="sub">// non-structural relationships</span>
        <span style={{marginLeft:'auto', fontFamily:'var(--mono)', fontSize:10.5, color:'var(--ink-4)'}}>
          {otherOut.length}↗ · {otherIn.length}↙
        </span>
      </header>
      <div>
        {Object.keys(out).sort().map(t => <Group key={'o'+t} type={t} items={out[t]} dir="out" />)}
        {Object.keys(inn).sort().map(t => <Group key={'i'+t} type={t} items={inn[t]} dir="in" />)}
      </div>
    </section>
  );
}

// simple deterministic hash (used for the stable REC id in the corner stamp)
function hashCode(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return h;
}

function CompositionPanel({ parents, kids }) {
  const router = useRouter();
  const idx = window.MYCELIUM_INDEX;

  const Item = ({ entry, n }) => {
    const t = entry.target;
    const out = (idx.outgoing[t.id] || []).filter(l => l.link_type === 'contains').length;
    const inn = (idx.incoming[t.id] || []).filter(l => l.link_type === 'contains').length;
    const otherOut = (idx.outgoing[t.id] || []).filter(l => l.link_type !== 'contains').length;
    return (
      <div className="comp-item" onClick={() => router.go({ view: 'statement', id: t.id })}>
        <span className="num">{String(n).padStart(2,'0')}</span>
        <div className="body">
          <div className="comp-title">{t.title || t.text}</div>
          <div className="comp-meta">
            <span className="id">{t.id}</span>
            <span title="parents">{inn}↑</span>
            <span title="children">{out}↓</span>
            <span title="other links">{otherOut}↗</span>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="composition">
      <div className="comp-col parents">
        <header className="comp-head">
          <span className="arrow">↑</span>
          <span>parents · this is a part of</span>
          <span className="ct">{parents.length}</span>
        </header>
        <div className="comp-list">
          {parents.length === 0 && <div className="comp-empty">// no parents — entry point</div>}
          {parents.map((p, i) => <Item key={p.target.id} entry={p} n={i+1} />)}
        </div>
      </div>
      <div className="comp-col children">
        <header className="comp-head">
          <span className="arrow">↓</span>
          <span>children · composed of</span>
          <span className="ct">{kids.length}</span>
        </header>
        <div className="comp-list">
          {kids.length === 0 && <div className="comp-empty">// leaf — no sub-statements</div>}
          {kids.map((c, i) => <Item key={c.target.id} entry={c} n={i+1} />)}
        </div>
      </div>
    </div>
  );
}

// Decorative statement glyph for the banner aside — encodes the 4 counts as a small radial.
function StatementGlyph({ parents, children, mentions, links }) {
  const cap = (n) => Math.min(8, n);
  const total = Math.max(1, parents + children + mentions + links);
  return (
    <svg viewBox="-50 -50 100 100">
      {/* concentric guide */}
      <circle cx="0" cy="0" r="42" fill="none" stroke="currentColor" strokeWidth="0.6" opacity="0.18" />
      <circle cx="0" cy="0" r="28" fill="none" stroke="currentColor" strokeWidth="0.6" opacity="0.18" />
      <circle cx="0" cy="0" r="14" fill="none" stroke="currentColor" strokeWidth="0.6" opacity="0.18" />
      {/* center node */}
      <circle cx="0" cy="0" r="5" fill="currentColor" />
      {/* parents above */}
      {Array.from({length: cap(parents)}).map((_, i) => {
        const angle = -Math.PI/2 + (i - (cap(parents)-1)/2) * 0.35;
        const x = Math.cos(angle) * 38, y = Math.sin(angle) * 38;
        return <g key={'p'+i}>
          <line x1="0" y1="0" x2={x} y2={y} stroke="#2563eb" strokeWidth="0.7" opacity="0.4" />
          <circle cx={x} cy={y} r="2.4" fill="#2563eb" />
        </g>;
      })}
      {/* children below */}
      {Array.from({length: cap(children)}).map((_, i) => {
        const angle = Math.PI/2 + (i - (cap(children)-1)/2) * 0.35;
        const x = Math.cos(angle) * 38, y = Math.sin(angle) * 38;
        return <g key={'c'+i}>
          <line x1="0" y1="0" x2={x} y2={y} stroke="currentColor" strokeWidth="0.7" opacity="0.45" />
          <circle cx={x} cy={y} r="2.4" fill="currentColor" />
        </g>;
      })}
      {/* mentions left */}
      {Array.from({length: cap(mentions)}).map((_, i) => {
        const angle = Math.PI + (i - (cap(mentions)-1)/2) * 0.28;
        const x = Math.cos(angle) * 26, y = Math.sin(angle) * 26;
        return <rect key={'m'+i} x={x-2} y={y-2} width="4" height="4" fill="#0e7490" transform={`rotate(45 ${x} ${y})`} />;
      })}
      {/* other links right */}
      {Array.from({length: cap(links)}).map((_, i) => {
        const angle = 0 + (i - (cap(links)-1)/2) * 0.28;
        const x = Math.cos(angle) * 26, y = Math.sin(angle) * 26;
        return <circle key={'l'+i} cx={x} cy={y} r="1.6" fill="#71717a" />;
      })}
    </svg>
  );
}

function ConnectionsRailSection({ dir, groups, count, idx }) {
  const router = useRouter();
  const isOut = dir === 'out';
  const types = Object.keys(groups).sort();
  return (
    <section className="rail-section">
      <header className="rail-head">
        <span className="title">
          <span className="arrow">{isOut ? '↗' : '↙'}</span>
          {isOut ? 'outgoing' : 'incoming'}
        </span>
        <span className="ct">{count}</span>
      </header>

      {count === 0 && (
        <div className="rail-empty">
          {isOut ? '// no outgoing links' : '// no incoming links'}
        </div>
      )}

      {types.map(type => {
        const items = groups[type];
        return (
          <div key={type} className={`linkgroup lt-${type}`}>
            <div className="linkgroup-head">
              <span className={`linktype-tag lt-${type}`}>{type}</span>
              <span className="linkgroup-count">{items.length}</span>
            </div>
            {items.map((l, i) => {
              const targetId = isOut ? l.to : l.from;
              const t = idx.byId[targetId];
              if (!t) return null;
              return (
                <div key={i} className={`linkrow lt-${type}`} onClick={() => router.go({ view: 'statement', id: targetId })}>
                  <div className="body">
                    {t.title || t.text}
                    <small>{targetId}</small>
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}
    </section>
  );
}

// ---------- Entity detail ----------

function EntityDetail({ id }) {
  const router = useRouter();
  const idx = window.MYCELIUM_INDEX;
  const e = idx.byId[id];

  if (!e || e.kind !== 'entity') return <NotFoundState what="entity" />;

  const aliases = idx.namesByEntity[e.id] || [];
  const mentioned = idx.mentionsByEntity[e.id] || [];
  const entityOutgoing = (idx.entityOutgoing[e.id] || [])
    .map(l => ({ ...l, target: idx.byId[l.to] }))
    .filter(x => x.target);
  const entityIncoming = (idx.entityIncoming[e.id] || [])
    .map(l => ({ ...l, target: idx.byId[l.from] }))
    .filter(x => x.target);
  const totalEntityLinks = entityOutgoing.length + entityIncoming.length;
  const directAnnotations = idx.annotationsByEntity[e.id] || [];
  const mentioningAnnotations = (idx.annotationsMentioningEntity[e.id] || [])
    .filter(a => !directAnnotations.some(d => d.id === a.id));

  return (
    <div className="detail">
      <DetailNav activeId={id} kind="entity" />

      <main className="detail-main">
        <div className="crumbs">
          <a href="#" onClick={(ev) => { ev.preventDefault(); router.go({ view: 'landing' }); }}>~</a>
          <span className="sep">/</span>
          <a href="#" onClick={(ev) => { ev.preventDefault(); router.go({ view: 'browse' }); }}>entities</a>
          <span className="sep">/</span>
          <span className="id">{e.id}</span>
        </div>

        <header className="entity-head" style={{marginTop:14}}>
          <div className="detail-kind">
            <KindTag kind="entity" />
            <span className="id">{e.id}</span>
            <EditHint>edit · v2</EditHint>
            <span className="stamp">
              <span><b>{aliases.length}</b> aliases</span>
              <span><b>{mentioned.length}</b>↙ mentions</span>
              {totalEntityLinks > 0 && <span><b>{totalEntityLinks}</b> entity links</span>}
              {(directAnnotations.length + mentioningAnnotations.length) > 0 && (
                <span><b>{directAnnotations.length + mentioningAnnotations.length}</b> annotations</span>
              )}
            </span>
          </div>
          <h1 className="entity-name">{e.name}</h1>
          <p className="entity-text">{e.description}</p>

          {aliases.length > 0 && (
            <div className="aliases">
              {aliases.map(n => <span key={n.id} className="alias">{n.text}</span>)}
            </div>
          )}
        </header>

        <AnnotationList
          title="annotations"
          sub="// typed propositions attached directly to this entity"
          annotations={directAnnotations}
          self={{ kind: 'entity', id: e.id }}
          style={{marginTop:24}}
        />

        {mentioningAnnotations.length > 0 && (
          <AnnotationList
            title="mentioning annotations"
            sub="// annotations that reference this entity but are attached elsewhere"
            annotations={mentioningAnnotations}
            self={{ kind: 'entity', id: e.id }}
            style={{marginTop:24}}
          />
        )}

        {totalEntityLinks > 0 && (
          <section style={{marginTop:24}}>
            <h3 className="section-title">
              <span>entity↔entity links</span>
              <span className="ct">{totalEntityLinks}</span>
            </h3>
            <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:24, marginTop:8}}>
              <div>
                <div style={{fontFamily:'var(--mono)', fontSize:11, color:'var(--ink-4)', marginBottom:6}}>
                  ↗ outgoing · {entityOutgoing.length}
                </div>
                {entityOutgoing.length === 0 && (
                  <div className="rail-empty">// none</div>
                )}
                {entityOutgoing.map((l, i) => (
                  <div
                    key={'eo' + i}
                    className="linkrow"
                    onClick={() => router.go({view:'entity', id: l.target.id})}
                    style={{paddingLeft:8}}
                  >
                    <span className={`linktype-tag lt-${l.link_type}`} style={{marginRight:8}}>{l.link_type}</span>
                    <div className="body">
                      {l.target.name}
                      <small>{l.target.id}</small>
                    </div>
                  </div>
                ))}
              </div>
              <div>
                <div style={{fontFamily:'var(--mono)', fontSize:11, color:'var(--ink-4)', marginBottom:6}}>
                  ↙ incoming · {entityIncoming.length}
                </div>
                {entityIncoming.length === 0 && (
                  <div className="rail-empty">// none</div>
                )}
                {entityIncoming.map((l, i) => (
                  <div
                    key={'ei' + i}
                    className="linkrow"
                    onClick={() => router.go({view:'entity', id: l.target.id})}
                    style={{paddingLeft:8}}
                  >
                    <span className={`linktype-tag lt-${l.link_type}`} style={{marginRight:8}}>{l.link_type}</span>
                    <div className="body">
                      {l.target.name}
                      <small>{l.target.id}</small>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        <section className="mentioned-by">
          <h3 className="section-title">
            <span>↙ mentioned by</span>
            <span className="ct">{mentioned.length}</span>
          </h3>
          <table className="tbl">
            <thead>
              <tr>
                <th style={{width:'1%'}}>#</th>
                <th style={{width:'1%'}}>id</th>
                <th>statement</th>
                <th style={{width:'1%', textAlign:'right'}}>mentions</th>
                <th style={{width:'1%', textAlign:'right'}}>links</th>
              </tr>
            </thead>
            <tbody>
              {mentioned.map((b, i) => (
                <tr key={b.id} onClick={() => router.go({ view: 'statement', id: b.id })}>
                  <td className="col-num">{String(i+1).padStart(2,'0')}</td>
                  <td className="col-id"><span className="row-id">{b.id}</span></td>
                  <td className="col-title">{b.title}</td>
                  <td className="col-meta">{(b.mentions||[]).length}</td>
                  <td className="col-meta">{(idx.outgoing[b.id]||[]).length}↗ {(idx.incoming[b.id]||[]).length}↙</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="inspect" style={{marginTop:18, padding:0}}>
            <div><span className="k">kind</span> <span className="v">entity</span></div>
            <div><span className="k">id</span> <span className="v">{e.id}</span></div>
            <div><span className="k">name</span> <span className="v">{e.name}</span></div>
            <div><span className="k">aliases</span> <span className="v">{aliases.length}</span></div>
            <div><span className="k">mentioned_by</span> <span className="v">{mentioned.length}</span></div>
            <div><span className="k">entity_links</span> <span className="v">{entityOutgoing.length}↗ {entityIncoming.length}↙</span></div>
            <div style={{marginTop:8}}>
              <a href="#" onClick={(ev) => { ev.preventDefault(); router.go({ view: 'graph', focus: e.id }); }}>
                graph.focus({e.id}) →
              </a>
            </div>
          </div>
        </section>
      </main>

      <aside className="detail-rail">
        <header className="rail-head">
          <span className="title">aliases</span>
          <span className="ct">{aliases.length}</span>
        </header>
        {aliases.length === 0 && <div className="rail-empty">// no aliases</div>}
        {aliases.map(n => (
          <div key={n.id} className="linkrow" style={{paddingLeft:12}} onClick={() => {}}>
            <div className="body" style={{fontFamily:'var(--mono)', fontSize:'var(--fs-xs)'}}>
              {n.text}
              <small>{n.id}</small>
            </div>
          </div>
        ))}

        <header className="rail-head" style={{marginTop:0}}>
          <span className="title">↙ mentioning statements</span>
          <span className="ct">{mentioned.length}</span>
        </header>
        {mentioned.length === 0 && <div className="rail-empty">// not mentioned anywhere</div>}
        {mentioned.map(b => (
          <div key={b.id} className="linkrow lt-mentions" onClick={() => router.go({view:'statement', id:b.id})}>
            <div className="body">
              {b.title}
              <small>{b.id}</small>
            </div>
          </div>
        ))}
      </aside>
    </div>
  );
}

// ---------- Browse index ----------

function BrowseIndex() {
  const router = useRouter();
  const data = window.MYCELIUM_DATA;
  const idx = window.MYCELIUM_INDEX;
  const [tab, setTab] = useStateS('statement');

  const counts = { entity: data.entities.length, statement: data.statements.length, name: data.names.length };

  return (
    <main className="page narrow">
      <div className="crumbs">
        <a href="#" onClick={(e) => { e.preventDefault(); router.go({ view: 'landing' }); }}>~</a>
        <span className="sep">/</span>
        <span>index</span>
      </div>
      <header className="results-head" style={{marginTop:8}}>
        <h1>index <span className="qct">{counts[tab]} rows</span></h1>
        <div className="results-tabs">
          {['statement', 'entity', 'name'].map(k => (
            <button key={k} className={tab === k ? 'is-active' : ''} onClick={() => setTab(k)}>
              {k}<span className="ct">{counts[k]}</span>
            </button>
          ))}
        </div>
      </header>

      {tab === 'statement' && (
        <BrowseStatementsTable data={data} idx={idx} onPick={(id) => router.go({ view: 'statement', id })} />
      )}

      {tab === 'entity' && (
        <table className="tbl">
          <thead>
            <tr>
              <th style={{width:'1%'}}>#</th>
              <th style={{width:'1%'}}>id</th>
              <th style={{width:'1%'}}>name</th>
              <th>description</th>
              <th style={{width:'1%', textAlign:'right'}}>aliases</th>
              <th style={{width:'1%', textAlign:'right'}}>mentioned</th>
            </tr>
          </thead>
          <tbody>
            {data.entities.map((e, i) => {
              const aliases = (idx.namesByEntity[e.id] || []).length;
              const mentions = (idx.mentionsByEntity[e.id] || []).length;
              return (
                <tr key={e.id} onClick={() => router.go({ view: 'entity', id: e.id })}>
                  <td className="col-num">{String(i+1).padStart(2,'0')}</td>
                  <td className="col-id"><span className="row-id">{e.id}</span></td>
                  <td className="col-title" style={{fontWeight:500}}>{e.name}</td>
                  <td className="col-title" style={{color:'var(--ink-3)'}}>{e.description}</td>
                  <td className="col-meta">{aliases}</td>
                  <td className="col-meta">{mentions}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {tab === 'name' && (
        <table className="tbl">
          <thead>
            <tr>
              <th style={{width:'1%'}}>#</th>
              <th style={{width:'1%'}}>id</th>
              <th style={{width:'1%'}}>text</th>
              <th>→ entity</th>
            </tr>
          </thead>
          <tbody>
            {data.names.map((n, i) => {
              const ent = idx.byId[n.entity];
              return (
                <tr key={n.id} onClick={() => router.go({ view: 'entity', id: n.entity })}>
                  <td className="col-num">{String(i+1).padStart(2,'0')}</td>
                  <td className="col-id"><span className="row-id">{n.id}</span></td>
                  <td className="col-title" style={{fontFamily:'var(--mono)', fontSize:'var(--fs-xs)'}}>“{n.text}”</td>
                  <td className="col-title">
                    <span style={{fontFamily:'var(--mono)', fontSize:'var(--fs-xs)', color:'var(--ink-4)'}}>{ent?.id}</span>
                    <span style={{marginLeft:10}}>{ent?.name}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </main>
  );
}

// Browse — statements table with claim-kind filter chips. The kinds in
// use are open vocabulary; we derive them from the corpus rather than
// hardcoding the starting trio (event/state/capability), so future kinds
// surface automatically.
function BrowseStatementsTable({ data, idx, onPick }) {
  const kindCounts = useMemoS(() => {
    const m = {};
    data.statements.forEach(b => { const k = b.kind || 'unknown'; m[k] = (m[k] || 0) + 1; });
    return m;
  }, [data]);
  const allKinds = Object.keys(kindCounts).sort();
  const [activeKinds, setActiveKinds] = useStateS(() => new Set(allKinds));

  // Re-init filter when corpus kinds change (a kind appearing for the
  // first time should be on by default, not silently filtered out).
  useEffectS(() => { setActiveKinds(new Set(allKinds)); }, [allKinds.join('|')]);

  const rows = data.statements.filter(b => activeKinds.has(b.kind || 'unknown'));

  return (
    <>
      <div className="results-tabs" style={{margin:'10px 0 14px'}}>
        {allKinds.map(k => {
          const on = activeKinds.has(k);
          return (
            <button
              key={k}
              className={on ? 'is-active' : ''}
              onClick={() => setActiveKinds(prev => {
                const next = new Set(prev);
                next.has(k) ? next.delete(k) : next.add(k);
                return next;
              })}
            >
              {k}<span className="ct">{kindCounts[k]}</span>
            </button>
          );
        })}
      </div>
      <table className="tbl">
        <thead>
          <tr>
            <th style={{width:'1%'}}>#</th>
            <th style={{width:'1%'}}>kind</th>
            <th style={{width:'1%'}}>id</th>
            <th>title</th>
            <th style={{width:'1%', textAlign:'right'}}>out</th>
            <th style={{width:'1%', textAlign:'right'}}>in</th>
            <th style={{width:'1%', textAlign:'right'}}>mentions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((b, i) => (
            <tr key={b.id} onClick={() => onPick(b.id)}>
              <td className="col-num">{String(i+1).padStart(2,'0')}</td>
              <td><ClaimKindTag kind={b.kind} /></td>
              <td className="col-id"><span className="row-id">{b.id}</span></td>
              <td className="col-title">{b.title}</td>
              <td className="col-meta">{(idx.outgoing[b.id]||[]).length}</td>
              <td className="col-meta">{(idx.incoming[b.id]||[]).length}</td>
              <td className="col-meta">{(b.mentions||[]).length}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

// ---------- Empty state ----------

function EmptyState({ title, blurb, suggestions = [], onSuggest }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      <p>{blurb}</p>
      {suggestions.length > 0 && (
        <div className="suggested">
          {suggestions.map(s => (
            <button key={s.id} className="chip" onClick={() => onSuggest?.(s.id)}>{s.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}

function NotFoundState({ what }) {
  const router = useRouter();
  return (
    <main className="page narrow">
      <EmptyState
        title={<>404 · {what} not found</>}
        blurb="The substrate trusts the writer; broken links happen during ingestion."
        suggestions={[
          { id: 'home', label: '← home' },
          { id: 'browse', label: 'open index' },
        ]}
        onSuggest={(id) => router.go({ view: id === 'home' ? 'landing' : 'browse' })}
      />
    </main>
  );
}

function LoadingDetail() {
  return (
    <main className="page">
      <div className="skeleton" style={{height:14, width:160, marginBottom:24}} />
      <div className="skeleton" style={{height:18, width:'60%', marginBottom:14}} />
      <div className="skeleton" style={{height:14, width:'90%', marginBottom:8}} />
      <div className="skeleton" style={{height:14, width:'80%', marginBottom:8}} />
      <div className="skeleton" style={{height:14, width:'85%'}} />
    </main>
  );
}

Object.assign(window, {
  Landing, SearchResults, StatementDetail, EntityDetail, BrowseIndex,
  EmptyState, NotFoundState, LoadingDetail,
});
