// Activity feed — paginated stream of mutations from history.history_events
// with a context panel that shows the affected target plus 1–2 hops of
// neighbors so the reviewer can judge whether the change reads correctly.

const { useState: useStateAct, useEffect: useEffectAct, useMemo: useMemoAct } = React;

const PAGE_SIZE = 50;

const OP_OPTIONS = ['create', 'update', 'link', 'attach'];
const KIND_OPTIONS = [
  'entity', 'statement', 'name', 'annotation',
  'statement_link', 'entity_link', 'entity_statement_link',
  'statement_annotation', 'entity_annotation',
];

function ActivityScreen({ page = 1, selected = null, ops = '', kinds = '', q = '' }) {
  const router = useRouter();
  const [state, setState] = useStateAct({ loading: true, error: null, events: [], total: 0 });
  const [qDraft, setQDraft] = useStateAct(q);

  // Keep the input synced when the URL changes from elsewhere (e.g. clicking a chip)
  useEffectAct(() => { setQDraft(q); }, [q]);

  useEffectAct(() => {
    let alive = true;
    setState(s => ({ ...s, loading: true, error: null }));
    const offset = (page - 1) * PAGE_SIZE;
    const qs = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (ops) qs.set('op', ops);
    if (kinds) qs.set('target_kind', kinds);
    if (q) qs.set('q', q);
    fetch(`/api/history?${qs.toString()}`, { headers: { accept: 'application/json' } })
      .then(r => r.ok ? r.json() : Promise.reject(new Error('GET /api/history → ' + r.status)))
      .then(d => { if (alive) setState({ loading: false, error: null, events: d.events || [], total: d.total || 0 }); })
      .catch(err => { if (alive) setState({ loading: false, error: err.message || String(err), events: [], total: 0 }); });
    return () => { alive = false; };
  }, [page, ops, kinds, q]);

  const totalPages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
  const selectedEvent = useMemoAct(
    () => state.events.find(e => String(e.event_id) === String(selected)) || null,
    [state.events, selected],
  );

  const opSet = useMemoAct(() => new Set(ops ? ops.split(',') : []), [ops]);
  const kindSet = useMemoAct(() => new Set(kinds ? kinds.split(',') : []), [kinds]);
  const hasFilters = opSet.size || kindSet.size || !!q;

  const updateFilters = (next) => router.go({
    view: 'activity',
    page: 1,
    selected: null,
    ops: next.ops !== undefined ? next.ops : ops,
    kinds: next.kinds !== undefined ? next.kinds : kinds,
    q: next.q !== undefined ? next.q : q,
  });

  const toggleSet = (set, value) => {
    const next = new Set(set);
    next.has(value) ? next.delete(value) : next.add(value);
    return [...next].join(',');
  };

  const submitQ = (e) => { e?.preventDefault(); if (qDraft !== q) updateFilters({ q: qDraft }); };

  return (
    <main className="page activity-page">
      <div className="crumbs">
        <a href="#" onClick={(e) => { e.preventDefault(); router.go({ view: 'landing' }); }}>~</a>
        <span className="sep">/</span>
        <span>activity</span>
      </div>

      <header className="results-head" style={{marginTop:8}}>
        <h1>activity <span className="qct">{state.total} events{hasFilters ? ' (filtered)' : ''}</span></h1>
        <div className="results-tabs">
          <button disabled={page <= 1} onClick={() => router.go({ view: 'activity', page: page - 1, ops, kinds, q })}>← prev</button>
          <span style={{fontFamily:'var(--mono)', fontSize:11, color:'var(--ink-3)', padding:'0 8px'}}>page {page} / {totalPages}</span>
          <button disabled={page >= totalPages} onClick={() => router.go({ view: 'activity', page: page + 1, ops, kinds, q })}>next →</button>
        </div>
      </header>

      <div className="activity-filters">
        <form onSubmit={submitQ} className="activity-search">
          <SearchIcon size={14} />
          <input
            type="text"
            value={qDraft}
            onChange={(e) => setQDraft(e.target.value)}
            onBlur={submitQ}
            placeholder="filter by target id substring…"
            spellCheck={false}
          />
          {qDraft && (
            <button type="button" className="activity-search-clear" onClick={() => { setQDraft(''); updateFilters({ q: '' }); }} title="clear">×</button>
          )}
        </form>

        <FilterChipGroup
          label="op"
          options={OP_OPTIONS}
          selected={opSet}
          onToggle={(v) => updateFilters({ ops: toggleSet(opSet, v) })}
        />

        <FilterChipGroup
          label="kind"
          options={KIND_OPTIONS}
          selected={kindSet}
          onToggle={(v) => updateFilters({ kinds: toggleSet(kindSet, v) })}
        />

        {hasFilters && (
          <button
            className="activity-filter-reset"
            onClick={() => updateFilters({ ops: '', kinds: '', q: '' })}
            title="clear all filters"
          >
            clear filters
          </button>
        )}
      </div>

      <div className="activity-layout">
        <div className="activity-list">
          {state.loading && <div className="muted" style={{padding:'12px 0'}}>loading…</div>}
          {state.error && <div className="muted" style={{padding:'12px 0', color:'var(--danger, #d04848)'}}>error: {state.error}</div>}
          {!state.loading && !state.error && state.events.length === 0 && (
            <div className="muted" style={{padding:'14px 0', fontFamily:'var(--mono)', fontSize:11}}>no events match these filters.</div>
          )}
          {!state.loading && !state.error && state.events.length > 0 && (
            <ActivityTable
              events={state.events}
              selectedId={selected}
              onPick={(ev) => router.go({ view: 'activity', page, ops, kinds, q, selected: String(ev.event_id) })}
              offset={(page - 1) * PAGE_SIZE}
            />
          )}
        </div>
        <aside className="activity-context">
          {selectedEvent ? (
            <ActivityContextPanel
              event={selectedEvent}
              onClose={() => router.go({ view: 'activity', page, ops, kinds, q })}
            />
          ) : (
            <div className="muted" style={{padding:'14px 4px', fontFamily:'var(--mono)', fontSize:11}}>
              select an event to see its context.
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}

function FilterChipGroup({ label, options, selected, onToggle }) {
  return (
    <div className="activity-filter-group">
      <span className="activity-filter-label">{label}</span>
      <div className="activity-filter-chips">
        {options.map(opt => {
          const on = selected.has(opt);
          return (
            <button
              key={opt}
              className={`activity-chip${on ? ' is-active' : ''}`}
              onClick={() => onToggle(opt)}
            >{opt}</button>
          );
        })}
      </div>
    </div>
  );
}

function ActivityTable({ events, selectedId, onPick, offset }) {
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th style={{width:'1%'}}>#</th>
          <th style={{width:'1%'}}>when</th>
          <th style={{width:'1%'}}>op</th>
          <th style={{width:'1%'}}>kind</th>
          <th>target</th>
          <th style={{width:'1%'}}>actor</th>
        </tr>
      </thead>
      <tbody>
        {events.map((ev, i) => {
          const isSel = String(ev.event_id) === String(selectedId);
          return (
            <tr key={ev.event_id} className={isSel ? 'is-selected' : ''} onClick={() => onPick(ev)}>
              <td className="col-num">{String(offset + i + 1).padStart(2,'0')}</td>
              <td className="col-meta" title={ev.at}>{formatAgo(ev.at)}</td>
              <td><OpTag op={ev.op} /></td>
              <td className="col-meta">{ev.target_kind}</td>
              <td className="col-title">{describeTarget(ev)}</td>
              <td className="col-meta">{ev.actor || '—'}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function OpTag({ op }) {
  const cls = {
    create: 'op-create', update: 'op-update', delete: 'op-delete',
    link: 'op-link', unlink: 'op-unlink', attach: 'op-attach', detach: 'op-detach',
  }[op] || 'op-other';
  return <span className={`tag ${cls}`} style={{fontFamily:'var(--mono)', fontSize:10.5}}>{op}</span>;
}

function describeTarget(ev) {
  const idx = window.MYCELIUM_INDEX;
  const data = window.MYCELIUM_DATA;
  const { target_kind: k, target_id: id } = ev;

  if (k === 'statement') {
    const cur = idx?.byId?.[id];
    return <><span className="row-id">{id}</span> {cur?.text ? <span style={{marginLeft:8}}>{truncate(cur.text, 100)}</span> : null}</>;
  }
  if (k === 'entity') {
    const cur = idx?.byId?.[id];
    return <><span className="row-id">{id}</span> <span style={{marginLeft:8, fontWeight:500}}>{cur?.name || id}</span></>;
  }
  if (k === 'name') {
    const cur = (data?.names || []).find(n => n.id === id);
    return <><span className="row-id">{id}</span> {cur?.text ? <span style={{marginLeft:8, fontFamily:'var(--mono)'}}>“{cur.text}”</span> : null}</>;
  }
  if (k === 'annotation') {
    const cur = idx?.byId?.[id];
    return <><span className="row-id">{id}</span> {cur?.text ? <span style={{marginLeft:8}}>{truncate(cur.text, 100)}</span> : null}</>;
  }
  if (k === 'statement_link' || k === 'entity_link') {
    const [from, to, type] = id.split('|');
    return (
      <span style={{fontFamily:'var(--mono)', fontSize:11}}>
        <span className="row-id">{from}</span>
        {' '}<span style={{color:'var(--accent)'}}>—{type || '?'}→</span>{' '}
        <span className="row-id">{to}</span>
      </span>
    );
  }
  if (k === 'entity_statement_link') {
    const [eid, bid, dir, type] = id.split('|');
    const [left, right] = dir === 'es' ? [eid, bid] : [bid, eid];
    return (
      <span style={{fontFamily:'var(--mono)', fontSize:11}}>
        <span className="row-id">{left}</span>
        {' '}<span style={{color:'var(--accent)'}}>—{type || '?'}→</span>{' '}
        <span className="row-id">{right}</span>
      </span>
    );
  }
  if (k === 'statement_annotation' || k === 'entity_annotation') {
    const [a, b] = id.split('|');
    return (
      <span style={{fontFamily:'var(--mono)', fontSize:11}}>
        <span className="row-id">{a}</span> ↔ <span className="row-id">{b}</span>
      </span>
    );
  }
  return <span className="row-id">{id}</span>;
}

function ActivityContextPanel({ event, onClose }) {
  return (
    <div className="ctx-panel">
      <div className="ctx-head">
        <div className="ctx-title">
          <OpTag op={event.op} /> <span style={{marginLeft:8, color:'var(--ink-3)'}}>{event.target_kind}</span>
        </div>
        <button className="ctx-close" onClick={onClose} title="close">×</button>
      </div>
      <div className="ctx-meta">
        <div><span className="lbl">at</span> <span>{event.at}</span></div>
        <div><span className="lbl">actor</span> <span>{event.actor || '—'}</span></div>
        <div><span className="lbl">id</span> <span className="row-id">{event.target_id}</span></div>
      </div>

      <div className="ctx-section-title">neighborhood</div>
      <ContextNeighbors event={event} />
    </div>
  );
}

// Build a small graph of nodes (1 anchor or 2 anchors for link events) +
// their 1-hop neighbors, so the reviewer can see the change in context.
function ContextNeighbors({ event }) {
  const router = useRouter();
  const idx = window.MYCELIUM_INDEX;
  const data = window.MYCELIUM_DATA;
  const { target_kind: k, target_id: id } = event;

  const model = useMemoAct(() => buildContextGraph(event, idx, data), [event, idx, data]);

  if (!model || model.anchors.length === 0) {
    return <div className="muted" style={{fontFamily:'var(--mono)', fontSize:11}}>no context resolvable</div>;
  }

  return <MiniGraph model={model} router={router} />;
}

// Returns { anchors: [{kind,id,node}], neighborsByAnchor: { anchorId: [{dir,id,kind,linkType}] }, anchorEdge: {linkType} | null }
function buildContextGraph(event, idx, data) {
  const { target_kind: k, target_id: id } = event;
  const MAX_PER_SIDE = 4;

  const resolveAnchor = (kind, anchorId) => {
    const node = idx?.byId?.[anchorId];
    return { kind, id: anchorId, node };
  };

  const neighborsForStatement = (sid) => {
    const out = (idx.outgoing[sid] || []).slice(0, MAX_PER_SIDE).map(l => ({ dir: 'out', id: l.to, kind: 'statement', linkType: l.link_type }));
    const inc = (idx.incoming[sid] || []).slice(0, MAX_PER_SIDE).map(l => ({ dir: 'in',  id: l.from, kind: 'statement', linkType: l.link_type }));
    return [...out, ...inc];
  };
  const neighborsForEntity = (eid) => {
    const out = (idx.entityOutgoing?.[eid] || []).slice(0, MAX_PER_SIDE).map(l => ({ dir: 'out', id: l.to, kind: 'entity', linkType: l.link_type }));
    const inc = (idx.entityIncoming?.[eid] || []).slice(0, MAX_PER_SIDE).map(l => ({ dir: 'in',  id: l.from, kind: 'entity', linkType: l.link_type }));
    const ments = (idx.mentionsByEntity?.[eid] || []).slice(0, MAX_PER_SIDE).map(b => ({ dir: 'mention', id: b.id, kind: 'statement', linkType: 'mentions' }));
    return [...out, ...inc, ...ments];
  };

  let anchors = [];
  let anchorEdge = null;

  if (k === 'statement' || k === 'annotation') anchors = [resolveAnchor(k, id)];
  else if (k === 'entity') anchors = [resolveAnchor('entity', id)];
  else if (k === 'name') {
    const n = (data?.names || []).find(x => x.id === id);
    if (n?.entity) anchors = [resolveAnchor('entity', n.entity)];
  } else if (k === 'statement_link') {
    const [from, to, type] = id.split('|');
    anchors = [resolveAnchor('statement', from), resolveAnchor('statement', to)];
    anchorEdge = { linkType: type };
  } else if (k === 'entity_link') {
    const [from, to, type] = id.split('|');
    anchors = [resolveAnchor('entity', from), resolveAnchor('entity', to)];
    anchorEdge = { linkType: type };
  } else if (k === 'entity_statement_link') {
    const [eid, bid, dir, type] = id.split('|');
    const a = resolveAnchor('entity', eid);
    const b = resolveAnchor('statement', bid);
    anchors = dir === 'es' ? [a, b] : [b, a];
    anchorEdge = { linkType: type };
  } else if (k === 'statement_annotation') {
    const [bid, aid] = id.split('|');
    anchors = [resolveAnchor('statement', bid), resolveAnchor('annotation', aid)];
    anchorEdge = { linkType: 'annotates' };
  } else if (k === 'entity_annotation') {
    const [eid, aid] = id.split('|');
    anchors = [resolveAnchor('entity', eid), resolveAnchor('annotation', aid)];
    anchorEdge = { linkType: 'annotates' };
  }

  const neighborsByAnchor = {};
  for (const a of anchors) {
    if (a.kind === 'statement') neighborsByAnchor[a.id] = neighborsForStatement(a.id);
    else if (a.kind === 'entity') neighborsByAnchor[a.id] = neighborsForEntity(a.id);
    else neighborsByAnchor[a.id] = [];
  }

  return { anchors, neighborsByAnchor, anchorEdge };
}

function labelFor(kind, id, idx, data) {
  if (kind === 'statement' || kind === 'annotation') {
    const n = idx?.byId?.[id];
    return n?.text || id;
  }
  if (kind === 'entity') {
    const n = idx?.byId?.[id];
    return n?.name || id;
  }
  if (kind === 'name') {
    const n = (data?.names || []).find(x => x.id === id);
    return n?.text || id;
  }
  return id;
}

function shapeFor(kind) {
  if (kind === 'entity') return 'circle';
  if (kind === 'annotation') return 'diamond';
  return 'rect';
}

function MiniGraph({ model, router }) {
  const data = window.MYCELIUM_DATA;
  const idx = window.MYCELIUM_INDEX;
  const W = 720;
  const ANCHOR_W = 220;
  const ANCHOR_H = 76;
  const NEIGHBOR_W = 170;
  const NEIGHBOR_H = 66;
  const ROW_GAP = 84;
  const COL_OUT_X = W - NEIGHBOR_W / 2 - 8;
  const COL_IN_X = NEIGHBOR_W / 2 + 8;

  const [tip, setTip] = useStateAct(null); // { x, y, linkType, fromKind, toKind } | null
  const linkTypeDescs = useLinkTypeDescriptions();

  // Stack two anchors vertically; everything is laid out per-anchor.
  // For each anchor: left column = incoming + mentions, right column = outgoing, anchor in middle.
  const groups = model.anchors.map((a, i) => {
    const items = model.neighborsByAnchor[a.id] || [];
    const outs = items.filter(it => it.dir === 'out');
    const ins  = items.filter(it => it.dir === 'in');
    const ments = items.filter(it => it.dir === 'mention');
    const leftItems = [...ins, ...ments];
    const rightItems = outs;
    const rowCount = Math.max(1, leftItems.length, rightItems.length);
    const height = Math.max(ANCHOR_H + 16, rowCount * ROW_GAP);
    return { anchor: a, leftItems, rightItems, height };
  });

  // Insert a connector edge band between two anchors (the change edge).
  const BAND_H = model.anchorEdge ? 38 : 0;

  let cursorY = 8;
  const renderedGroups = groups.map((g, gi) => {
    const top = cursorY;
    const cy = top + g.height / 2;
    const anchorPt = { x: W / 2, y: cy };

    const leftPts = g.leftItems.map((it, i) => {
      const slots = g.leftItems.length;
      const y = top + ((i + 0.5) / slots) * g.height;
      return { x: COL_IN_X, y, item: it };
    });
    const rightPts = g.rightItems.map((it, i) => {
      const slots = g.rightItems.length;
      const y = top + ((i + 0.5) / slots) * g.height;
      return { x: COL_OUT_X, y, item: it };
    });

    cursorY = top + g.height + (gi < groups.length - 1 ? BAND_H : 0);

    return { ...g, top, anchorPt, leftPts, rightPts };
  });

  const totalH = cursorY + 8;

  const nav = (kind, id) => {
    const view = kind === 'entity' ? 'entity'
      : kind === 'statement' ? 'statement'
      : null;
    if (view) router.go({ view, id });
  };

  return (
    <svg className="ctx-mini-graph" viewBox={`0 0 ${W} ${totalH}`} width="100%" height={totalH}>
      <defs>
        <marker id="ctx-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
        </marker>
        <marker id="ctx-arrow-accent" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" className="ctx-arrow-accent-fill" />
        </marker>
      </defs>

      {renderedGroups.map((g, gi) => (
        <g key={g.anchor.id}>
          {/* incoming edges (left → anchor) */}
          {g.leftPts.map((pt, i) => (
            <EdgeLine
              key={`l-${i}`}
              from={pt} fromHalfW={NEIGHBOR_W/2}
              to={g.anchorPt} toHalfW={ANCHOR_W/2}
              label={pt.item.linkType}
              dashed={pt.item.dir === 'mention'}
              fromKind={pt.item.kind}
              toKind={g.anchor.kind}
              onHover={setTip}
            />
          ))}
          {/* outgoing edges (anchor → right) */}
          {g.rightPts.map((pt, i) => (
            <EdgeLine
              key={`r-${i}`}
              from={g.anchorPt} fromHalfW={ANCHOR_W/2}
              to={pt} toHalfW={NEIGHBOR_W/2}
              label={pt.item.linkType}
              fromKind={g.anchor.kind}
              toKind={pt.item.kind}
              onHover={setTip}
            />
          ))}

          {/* anchor node */}
          <GraphNode
            x={g.anchorPt.x} y={g.anchorPt.y}
            w={ANCHOR_W} h={ANCHOR_H}
            kind={g.anchor.kind}
            id={g.anchor.id}
            label={labelFor(g.anchor.kind, g.anchor.id, idx, data)}
            anchor
            onClick={() => nav(g.anchor.kind, g.anchor.id)}
          />

          {/* neighbor nodes */}
          {g.leftPts.map((pt, i) => (
            <GraphNode
              key={`ln-${i}`}
              x={pt.x} y={pt.y} w={NEIGHBOR_W} h={NEIGHBOR_H}
              kind={pt.item.kind}
              id={pt.item.id}
              label={labelFor(pt.item.kind, pt.item.id, idx, data)}
              onClick={() => nav(pt.item.kind, pt.item.id)}
            />
          ))}
          {g.rightPts.map((pt, i) => (
            <GraphNode
              key={`rn-${i}`}
              x={pt.x} y={pt.y} w={NEIGHBOR_W} h={NEIGHBOR_H}
              kind={pt.item.kind}
              id={pt.item.id}
              label={labelFor(pt.item.kind, pt.item.id, idx, data)}
              onClick={() => nav(pt.item.kind, pt.item.id)}
            />
          ))}

          {/* change-edge between two anchors */}
          {model.anchorEdge && gi === 0 && renderedGroups[1] && (
            <ChangeEdge
              from={g.anchorPt}
              to={renderedGroups[1].anchorPt}
              halfH={ANCHOR_H/2}
              label={model.anchorEdge.linkType}
              fromKind={g.anchor.kind}
              toKind={renderedGroups[1].anchor.kind}
              onHover={setTip}
            />
          )}
        </g>
      ))}
      {tip && (
        <EdgeTooltip
          x={tip.x} y={tip.y}
          svgW={W}
          linkType={tip.linkType}
          description={linkTypeDescs[`${tip.fromKind}|${tip.linkType}|${tip.toKind}`] || linkTypeDescs[tip.linkType]}
          fromKind={tip.fromKind} toKind={tip.toKind}
        />
      )}
    </svg>
  );
}

// Cache link-type descriptions across renders. Fetches from the substrate
// glossary (statement_link / entity_link / entity_statement_link types).
function useLinkTypeDescriptions() {
  const [map, setMap] = useStateAct(() => window.__MYC_LINK_TYPE_DESC || {});
  useEffectAct(() => {
    if (window.__MYC_LINK_TYPE_DESC) return;
    Promise.all([
      fetch('/list-link-types').then(r => r.ok ? r.json() : []).catch(() => []),
      fetch('/list-entity-link-types').then(r => r.ok ? r.json() : []).catch(() => []),
    ]).then(([sl, el]) => {
      const m = {};
      (sl || []).forEach(t => { if (t.link_type) m[t.link_type] = t.description || ''; });
      (el || []).forEach(t => { if (t.link_type) m[t.link_type] = t.description || ''; });
      window.__MYC_LINK_TYPE_DESC = m;
      setMap(m);
    });
  }, []);
  return map;
}

function EdgeTooltip({ x, y, svgW, linkType, description, fromKind, toKind }) {
  // Clamp horizontally so the tooltip stays in the panel.
  const W = 240;
  const H = description ? 64 : 32;
  let tx = Math.max(6, Math.min(svgW - W - 6, x - W / 2));
  let ty = y - H - 12;
  if (ty < 6) ty = y + 14;
  return (
    <g className="ctx-edge-tooltip" pointerEvents="none">
      <rect x={tx} y={ty} width={W} height={H} rx={5} className="ctx-edge-tooltip-bg" />
      <foreignObject x={tx + 8} y={ty + 6} width={W - 16} height={H - 12}>
        <div xmlns="http://www.w3.org/1999/xhtml" className="ctx-edge-tooltip-body">
          <div className="ctx-edge-tooltip-head">
            <span className="ctx-edge-tooltip-type">{linkType}</span>
            <span className="ctx-edge-tooltip-pair">{fromKind} → {toKind}</span>
          </div>
          {description && <div className="ctx-edge-tooltip-desc">{description}</div>}
        </div>
      </foreignObject>
    </g>
  );
}

function EdgeLine({ from, fromHalfW, to, toHalfW, label, dashed, fromKind, toKind, onHover }) {
  // Endpoints are the centers; offset so the line ends at the node edge.
  const x1 = from.x < to.x ? from.x + fromHalfW : from.x - fromHalfW;
  const x2 = from.x < to.x ? to.x - toHalfW : to.x + toHalfW;
  const mx = (x1 + x2) / 2;
  const my = (from.y + to.y) / 2 - 6;
  const pillW = label ? Math.max(38, label.length * 7 + 12) : 0;
  const enter = () => onHover && onHover({ x: mx, y: my, linkType: label, fromKind, toKind });
  const leave = () => onHover && onHover(null);
  return (
    <g className="ctx-edge" onMouseEnter={enter} onMouseLeave={leave}>
      {/* invisible thick hit-area for easier hover */}
      <line x1={x1} y1={from.y} x2={x2} y2={to.y} className="ctx-edge-hit" />
      <line
        x1={x1} y1={from.y} x2={x2} y2={to.y}
        strokeDasharray={dashed ? '3 3' : undefined}
        markerEnd="url(#ctx-arrow)"
      />
      {label && (
        <>
          <rect x={mx - pillW/2} y={my - 10} width={pillW} height={16} rx={3} className="ctx-edge-label-pill" />
          <text x={mx} y={my + 2} textAnchor="middle" className="ctx-edge-label">{label}</text>
        </>
      )}
    </g>
  );
}

function ChangeEdge({ from, to, halfH, label, fromKind, toKind, onHover }) {
  // The change edge is between two stacked anchors — vertical.
  const x = from.x;
  const y1 = from.y + halfH;
  const y2 = to.y - halfH;
  const my = (y1 + y2) / 2;
  const pillW = Math.max(72, label.length * 7 + 18);
  const enter = () => onHover && onHover({ x, y: my, linkType: label, fromKind, toKind });
  const leave = () => onHover && onHover(null);
  return (
    <g className="ctx-change-edge" onMouseEnter={enter} onMouseLeave={leave}>
      <line x1={x} y1={y1} x2={x} y2={y2} className="ctx-edge-hit" />
      <line x1={x} y1={y1} x2={x} y2={y2} markerEnd="url(#ctx-arrow-accent)" />
      <rect x={x - pillW/2} y={my - 11} width={pillW} height={22} rx={5} className="ctx-change-edge-pill" />
      <text x={x} y={my + 5} textAnchor="middle" className="ctx-change-edge-label">{label}</text>
    </g>
  );
}

function GraphNode({ x, y, w, h, kind, id, label, anchor, onClick }) {
  const shape = shapeFor(kind);
  const cls = `ctx-node ctx-node-${kind}${anchor ? ' ctx-node-anchor' : ''}${onClick ? '' : ' ctx-node-disabled'}`;
  return (
    <g className={cls} transform={`translate(${x - w/2}, ${y - h/2})`} onClick={onClick} style={{ cursor: onClick ? 'pointer' : 'default' }}>
      <title>{`${id}\n${label}`}</title>
      {shape === 'rect' && <rect x={0} y={0} width={w} height={h} rx={5} />}
      {shape === 'circle' && <rect x={0} y={0} width={w} height={h} rx={h/2} />}
      {shape === 'diamond' && (
        <polygon points={`${w/2},0 ${w},${h/2} ${w/2},${h} 0,${h/2}`} />
      )}
      <foreignObject x={6} y={4} width={w - 12} height={h - 8}>
        <div xmlns="http://www.w3.org/1999/xhtml" className="ctx-node-body">
          <div className="ctx-node-id-row">{id.slice(0, 16)}</div>
          <div className="ctx-node-label-row">{label}</div>
        </div>
      </foreignObject>
    </g>
  );
}

function truncate(s, n) {
  if (!s) return '';
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

function formatAgo(iso) {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const secs = Math.max(0, (Date.now() - t) / 1000);
  if (secs < 60) return `${Math.floor(secs)}s ago`;
  const mins = secs / 60;
  if (mins < 60) return `${Math.floor(mins)}m ago`;
  const hrs = mins / 60;
  if (hrs < 24) return `${Math.floor(hrs)}h ago`;
  const days = hrs / 24;
  if (days < 30) return `${Math.floor(days)}d ago`;
  return iso.slice(0, 10);
}

Object.assign(window, { ActivityScreen });
