// Activity feed — paginated stream of mutations from history.history_events
// with a context panel that shows the affected target plus 1–2 hops of
// neighbors so the reviewer can judge whether the change reads correctly.
import { useState as useStateAct, useEffect as useEffectAct, useMemo as useMemoAct } from 'react';
import { errorMessage, getActivity, getJSON, type ActivityEvent } from './api';
import { I, PageHeader } from './lib';
import { useRouter, type Router } from './router';
import { substrate, type IndexedRecord, type SubstrateData, type SubstrateIndex } from './data';

const PAGE_SIZE = 50;

const OP_OPTIONS = ['create', 'update', 'link', 'attach'];
const KIND_OPTIONS = [
  'entity', 'statement', 'name',
  'statement_link', 'entity_link', 'entity_statement_link',
];

interface ActivityState { loading: boolean; error: string | null; events: ActivityEvent[]; total: number }
interface ActivityFilters { ops?: string; kinds?: string; q?: string }
type GraphKind = 'entity' | 'statement';
type NeighborDirection = 'out' | 'in' | 'mention';
interface ContextAnchor { kind: GraphKind; id: string; node: IndexedRecord | undefined }
interface ContextNeighbor { dir: NeighborDirection; id: string; kind: GraphKind; linkType: string }
interface ContextGraph {
  anchors: ContextAnchor[];
  neighborsByAnchor: Record<string, ContextNeighbor[]>;
  anchorEdge: { linkType: string } | null;
}

function ActivityScreen({ page = 1, selected = null, ops = '', kinds = '', q = '' }: {
  page?: number; selected?: string | null; ops?: string; kinds?: string; q?: string;
}) {
  const router = useRouter();
  const [state, setState] = useStateAct<ActivityState>({ loading: true, error: null, events: [], total: 0 });
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
    getActivity(qs)
      .then(d => { if (alive) setState({ loading: false, error: null, events: d.events || [], total: d.total || 0 }); })
      .catch(err => { if (alive) setState({ loading: false, error: errorMessage(err), events: [], total: 0 }); });
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

  const updateFilters = (next: ActivityFilters) => router.go({
    view: 'activity',
    page: 1,
    selected: null,
    ops: next.ops !== undefined ? next.ops : ops,
    kinds: next.kinds !== undefined ? next.kinds : kinds,
    q: next.q !== undefined ? next.q : q,
  });

  const toggleSet = (set: Set<string>, value: string) => {
    const next = new Set(set);
    next.has(value) ? next.delete(value) : next.add(value);
    return [...next].join(',');
  };

  const submitQ = (e?: { preventDefault: () => void }) => { e?.preventDefault(); if (qDraft !== q) updateFilters({ q: qDraft }); };

  return (
    <main className="page activity-page">
      <PageHeader eyebrow="Curate" title="Activity"
        blurb={<>Every change to the knowledge base, newest first. Select an event to see what it touched in context. {state.total} event{state.total === 1 ? '' : 's'}{hasFilters ? ' match these filters' : ''}.</>}
        actions={<div className="pager">
          <button className="btn ghost sm" disabled={page <= 1} onClick={() => router.go({ view: 'activity', page: page - 1, ops, kinds, q, selected: null })}>← Newer</button>
          <span className="mono small muted">page {page} / {totalPages}</span>
          <button className="btn ghost sm" disabled={page >= totalPages} onClick={() => router.go({ view: 'activity', page: page + 1, ops, kinds, q, selected: null })}>Older →</button>
        </div>} />

      <div className="activity-filters">
        <form onSubmit={submitQ} className="activity-search">
          <I.find width={14} height={14} />
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

      <div className={`activity-layout${selectedEvent ? ' has-context' : ''}`}>
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
        {selectedEvent && (
          <aside className="activity-context">
            <ActivityContextPanel
              event={selectedEvent}
              onClose={() => router.go({ view: 'activity', page, ops, kinds, q, selected: null })}
            />
          </aside>
        )}
      </div>
    </main>
  );
}

function FilterChipGroup({ label, options, selected, onToggle }: {
  label: string; options: string[]; selected: Set<string>; onToggle: (value: string) => void;
}) {
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

function ActivityTable({ events, selectedId, onPick, offset }: {
  events: ActivityEvent[]; selectedId: string | null; onPick: (event: ActivityEvent) => void; offset: number;
}) {
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

function OpTag({ op }: { op: string }) {
  const classes: Record<string, string> = {
    create: 'op-create', update: 'op-update', delete: 'op-delete',
    link: 'op-link', unlink: 'op-unlink', attach: 'op-attach', detach: 'op-detach',
  };
  const cls = classes[op] || 'op-other';
  return <span className={`tag ${cls}`} style={{fontFamily:'var(--mono)', fontSize:10.5}}>{op}</span>;
}

function describeTarget(ev: ActivityEvent) {
  const idx = substrate.index;
  const data = substrate.data;
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
  if (k === 'statement_link' || k === 'entity_link') {
    const [from = '', to = '', type = ''] = id.split('|');
    return (
      <span style={{fontFamily:'var(--mono)', fontSize:11}}>
        <span className="row-id">{from}</span>
        {' '}<span style={{color:'var(--accent)'}}>—{type || '?'}→</span>{' '}
        <span className="row-id">{to}</span>
      </span>
    );
  }
  if (k === 'entity_statement_link') {
    const [eid = '', bid = '', dir = '', type = ''] = id.split('|');
    const [left, right] = dir === 'es' ? [eid, bid] : [bid, eid];
    return (
      <span style={{fontFamily:'var(--mono)', fontSize:11}}>
        <span className="row-id">{left}</span>
        {' '}<span style={{color:'var(--accent)'}}>—{type || '?'}→</span>{' '}
        <span className="row-id">{right}</span>
      </span>
    );
  }
  return <span className="row-id">{id}</span>;
}

function ActivityContextPanel({ event, onClose }: { event: ActivityEvent; onClose: () => void }) {
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
function ContextNeighbors({ event }: { event: ActivityEvent }) {
  const router = useRouter();
  const idx = substrate.index;
  const data = substrate.data;

  const model = useMemoAct(() => buildContextGraph(event, idx, data), [event, idx, data]);

  if (!model || model.anchors.length === 0) {
    return <div className="muted" style={{fontFamily:'var(--mono)', fontSize:11}}>no context resolvable</div>;
  }

  return <MiniGraph model={model} router={router} />;
}

// Returns { anchors: [{kind,id,node}], neighborsByAnchor: { anchorId: [{dir,id,kind,linkType}] }, anchorEdge: {linkType} | null }
function buildContextGraph(event: ActivityEvent, idx: SubstrateIndex, data: SubstrateData): ContextGraph {
  const { target_kind: k, target_id: id } = event;
  const MAX_PER_SIDE = 4;

  const resolveAnchor = (kind: GraphKind, anchorId: string): ContextAnchor => {
    const node = idx?.byId?.[anchorId];
    return { kind, id: anchorId, node };
  };

  const neighborsForStatement = (sid: string): ContextNeighbor[] => {
    const out = (idx.outgoing[sid] || []).slice(0, MAX_PER_SIDE).map((l): ContextNeighbor => ({ dir: 'out', id: l.to, kind: 'statement', linkType: l.link_type }));
    const inc = (idx.incoming[sid] || []).slice(0, MAX_PER_SIDE).map((l): ContextNeighbor => ({ dir: 'in',  id: l.from, kind: 'statement', linkType: l.link_type }));
    return [...out, ...inc];
  };
  const neighborsForEntity = (eid: string): ContextNeighbor[] => {
    const out = (idx.entityOutgoing[eid] || []).slice(0, MAX_PER_SIDE).map((l): ContextNeighbor => ({ dir: 'out', id: l.to, kind: 'entity', linkType: l.link_type }));
    const inc = (idx.entityIncoming[eid] || []).slice(0, MAX_PER_SIDE).map((l): ContextNeighbor => ({ dir: 'in',  id: l.from, kind: 'entity', linkType: l.link_type }));
    const ments = (idx.mentionsByEntity[eid] || []).slice(0, MAX_PER_SIDE).map((b): ContextNeighbor => ({ dir: 'mention', id: b.id, kind: 'statement', linkType: 'mentions' }));
    return [...out, ...inc, ...ments];
  };

  let anchors: ContextAnchor[] = [];
  let anchorEdge: ContextGraph['anchorEdge'] = null;

  if (k === 'statement') anchors = [resolveAnchor(k, id)];
  else if (k === 'entity') anchors = [resolveAnchor('entity', id)];
  else if (k === 'name') {
    const n = (data?.names || []).find(x => x.id === id);
    if (n?.entity) anchors = [resolveAnchor('entity', n.entity)];
  } else if (k === 'statement_link') {
    const [from = '', to = '', type = ''] = id.split('|');
    anchors = [resolveAnchor('statement', from), resolveAnchor('statement', to)];
    anchorEdge = { linkType: type };
  } else if (k === 'entity_link') {
    const [from = '', to = '', type = ''] = id.split('|');
    anchors = [resolveAnchor('entity', from), resolveAnchor('entity', to)];
    anchorEdge = { linkType: type };
  } else if (k === 'entity_statement_link') {
    const [eid = '', bid = '', dir = '', type = ''] = id.split('|');
    const a = resolveAnchor('entity', eid);
    const b = resolveAnchor('statement', bid);
    anchors = dir === 'es' ? [a, b] : [b, a];
    anchorEdge = { linkType: type };
  }

  const neighborsByAnchor: Record<string, ContextNeighbor[]> = {};
  for (const a of anchors) {
    if (a.kind === 'statement') neighborsByAnchor[a.id] = neighborsForStatement(a.id);
    else if (a.kind === 'entity') neighborsByAnchor[a.id] = neighborsForEntity(a.id);
    else neighborsByAnchor[a.id] = [];
  }

  return { anchors, neighborsByAnchor, anchorEdge };
}

function labelFor(kind: string, id: string, idx: SubstrateIndex, data: SubstrateData): string {
  if (kind === 'statement') {
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

function shapeFor(kind: string) {
  if (kind === 'entity') return 'circle';
  return 'rect';
}

function MiniGraph({ model, router }: { model: ContextGraph; router: Router }) {
  const data = substrate.data;
  const idx = substrate.index;
  const W = 720;
  const ANCHOR_W = 220;
  const ANCHOR_H = 76;
  const NEIGHBOR_W = 170;
  const NEIGHBOR_H = 66;
  const ROW_GAP = 84;
  const COL_OUT_X = W - NEIGHBOR_W / 2 - 8;
  const COL_IN_X = NEIGHBOR_W / 2 + 8;

  const [tip, setTip] = useStateAct<EdgeTip | null>(null);
  const linkTypeDescs = useLinkTypeDescriptions();

  // Stack two anchors vertically; everything is laid out per-anchor.
  // For each anchor: left column = incoming + mentions, right column = outgoing, anchor in middle.
  const groups = model.anchors.map((a) => {
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

  const nav = (kind: GraphKind, id: string) => {
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
let linkTypeDescriptions: Record<string, string> | null = null;

function useLinkTypeDescriptions(): Record<string, string> {
  const [map, setMap] = useStateAct(() => linkTypeDescriptions || {});
  useEffectAct(() => {
    if (linkTypeDescriptions) return;
    Promise.all([
      getJSON<{ link_type: string; description?: string | null }[]>('/list-link-types').catch(() => []),
      getJSON<{ link_type: string; description?: string | null }[]>('/list-entity-link-types').catch(() => []),
    ]).then(([sl, el]) => {
      const m: Record<string, string> = {};
      (sl || []).forEach(t => { if (t.link_type) m[t.link_type] = t.description || ''; });
      (el || []).forEach(t => { if (t.link_type) m[t.link_type] = t.description || ''; });
      linkTypeDescriptions = m;
      setMap(m);
    });
  }, []);
  return map;
}

function EdgeTooltip({ x, y, svgW, linkType, description, fromKind, toKind }: {
  x: number; y: number; svgW: number; linkType: string; description?: string;
  fromKind: string; toKind: string;
}) {
  // Clamp horizontally so the tooltip stays in the panel.
  const W = 240;
  const H = description ? 64 : 32;
  const tx = Math.max(6, Math.min(svgW - W - 6, x - W / 2));
  let ty = y - H - 12;
  if (ty < 6) ty = y + 14;
  return (
    <g className="ctx-edge-tooltip" pointerEvents="none">
      <rect x={tx} y={ty} width={W} height={H} rx={5} className="ctx-edge-tooltip-bg" />
      <foreignObject x={tx + 8} y={ty + 6} width={W - 16} height={H - 12}>
        <div className="ctx-edge-tooltip-body">
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

interface Point { x: number; y: number }
interface EdgeTip { x: number; y: number; linkType: string; fromKind: string; toKind: string }

function EdgeLine({ from, fromHalfW, to, toHalfW, label, dashed, fromKind, toKind, onHover }: {
  from: Point; fromHalfW: number; to: Point; toHalfW: number; label?: string; dashed?: boolean;
  fromKind: string; toKind: string; onHover?: (tip: EdgeTip | null) => void;
}) {
  // Endpoints are the centers; offset so the line ends at the node edge.
  const x1 = from.x < to.x ? from.x + fromHalfW : from.x - fromHalfW;
  const x2 = from.x < to.x ? to.x - toHalfW : to.x + toHalfW;
  const mx = (x1 + x2) / 2;
  const my = (from.y + to.y) / 2 - 6;
  const pillW = label ? Math.max(38, label.length * 7 + 12) : 0;
  const enter = () => onHover && onHover({ x: mx, y: my, linkType: label || '', fromKind, toKind });
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

function ChangeEdge({ from, to, halfH, label, fromKind, toKind, onHover }: {
  from: Point; to: Point; halfH: number; label: string; fromKind: string; toKind: string;
  onHover?: (tip: EdgeTip | null) => void;
}) {
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

function GraphNode({ x, y, w, h, kind, id, label, anchor, onClick }: {
  x: number; y: number; w: number; h: number; kind: string; id: string; label: string;
  anchor?: boolean; onClick?: () => void;
}) {
  const shape = shapeFor(kind);
  const cls = `ctx-node ctx-node-${kind}${anchor ? ' ctx-node-anchor' : ''}${onClick ? '' : ' ctx-node-disabled'}`;
  return (
    <g className={cls} transform={`translate(${x - w/2}, ${y - h/2})`} onClick={onClick} style={{ cursor: onClick ? 'pointer' : 'default' }}>
      <title>{`${id}\n${label}`}</title>
      {shape === 'rect' && <rect x={0} y={0} width={w} height={h} rx={5} />}
      {shape === 'circle' && <rect x={0} y={0} width={w} height={h} rx={h/2} />}
      <foreignObject x={6} y={4} width={w - 12} height={h - 8}>
        <div className="ctx-node-body">
          <div className="ctx-node-id-row">{id.slice(0, 16)}</div>
          <div className="ctx-node-label-row">{label}</div>
        </div>
      </foreignObject>
    </g>
  );
}

function truncate(s: string, n: number) {
  if (!s) return '';
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

function formatAgo(iso: string) {
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

export { ActivityScreen };
