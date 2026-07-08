// Drafts screen — review pending change sets queued by drafters (or
// any caller passing an explicit draft_id). Curators approve (replay
// against the substrate) or reject (drop without applying).
//
// Two views, picked by the `selected` prop:
//   - list view: status-filtered list of drafts with op counts.
//   - detail view: one draft's ops in seq order, payload pretty-printed,
//     with approve/reject/withdraw buttons + per-op remove.
//
// Scoped graph of the draft's touched entities/statements is deferred
// to a follow-up — list+detail is enough to validate the flow end-to-end.

const { useState: useD, useEffect: useED, useCallback: useCBD, useMemo: useMD } = React;


async function _fetchDrafts(status) {
  const url = status && status !== 'all'
    ? `/api/drafts?status=${status}`
    : '/api/drafts';
  const r = await fetch(url);
  if (!r.ok) {
    let d; try { d = (await r.json()).detail; } catch (_) { d = r.statusText; }
    throw new Error(d || `${url} → ${r.status}`);
  }
  return r.json();
}

async function _fetchDraftDetail(draftId) {
  const r = await fetch(`/api/drafts/${draftId}`);
  if (!r.ok) {
    let d; try { d = (await r.json()).detail; } catch (_) { d = r.statusText; }
    throw new Error(d || `${draftId} → ${r.status}`);
  }
  return r.json();
}

async function _draftAction(draftId, action) {
  const r = await fetch(`/api/drafts/${draftId}/${action}`, { method: 'POST' });
  if (!r.ok) {
    let d; try { d = (await r.json()).detail; } catch (_) { d = r.statusText; }
    throw new Error(d || `${action} → ${r.status}`);
  }
  return r.json();
}

async function _removeOp(draftId, seq) {
  const r = await fetch(`/api/drafts/${draftId}/ops/${seq}`, { method: 'DELETE' });
  if (!r.ok) {
    let d; try { d = (await r.json()).detail; } catch (_) { d = r.statusText; }
    throw new Error(d || `DELETE seq ${seq} → ${r.status}`);
  }
  return r.json();
}

async function _editOp(draftId, seq, payload) {
  const r = await fetch(`/api/drafts/${draftId}/ops/${seq}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ payload }),
  });
  if (!r.ok) {
    let d; try { d = (await r.json()).detail; } catch (_) { d = r.statusText; }
    throw new Error(d || `PATCH seq ${seq} → ${r.status}`);
  }
  return r.json();
}


// ---------- Scoped graph (draft detail) ----------
//
// Reuses the main GraphView by feeding it a scoped substrate-shape
// dataset. The shape is the same as what `/api/data` returns
// (entities, statements, names, links, entity_links);
// `buildIndex` produces a matching index. GraphView's render code +
// interactions (pan, zoom, drag, highlight, sidepanel) all work
// unchanged — no parallel viewer to keep in lockstep.
//
// What goes into the scoped data:
//   - Every entity / statement touched by an op in the draft.
//   - Newly-created entities / statements appear as synthetic rows with
//     placeholder ids (`_draft_ent_N`, `_draft_stm_N`) so the layout
//     engine sees them as first-class nodes.
//   - For each existing-substrate node we touched, one hop of substrate
//     neighbors comes along for context.
//
// Limitation worth flagging: the draft view doesn't visually distinguish
// "introduced by this draft" from "existing-substrate context" yet —
// they share the same node styling. The win here is consistency of
// interaction and visual language. A highlight overlay can layer on
// top of GraphView later without forking the renderer.

function _buildScopedSubstrate(ops, full) {
  const ents = new Map((full.entities || []).map(e => [e.id, e]));
  const stmts = new Map((full.statements || []).map(s => [s.id, s]));
  const namesByEntity = new Map();
  (full.names || []).forEach(n => {
    if (!namesByEntity.has(n.entity)) namesByEntity.set(n.entity, []);
    namesByEntity.get(n.entity).push(n);
  });

  const touchedEnt = new Set();
  const touchedStm = new Set();
  const synthEnts = [];   // newly-introduced entities (no real id yet)
  const synthStmts = [];  // newly-introduced statements (no real id yet)
  const synthNames = [];  // names for synthetic entities
  const synthLinks = [];        // statement→statement links queued
  const synthEntLinks = [];     // entity→entity links queued
  const synthMentionsByStm = {}; // statement_id → [entity_id] for queued mentions

  let synthCount = 0;
  const newId = (kind) => `_draft_${kind}_${synthCount++}`;

  // Index existing names by text so an upsert_entity for an existing
  // name resolves to the real id instead of producing a duplicate node.
  const nameByText = new Map((full.names || []).map(n => [n.text, n]));

  for (const op of ops || []) {
    const p = op.payload || {};
    if (op.kind === 'upsert_entity') {
      const existing = nameByText.get(p.name);
      if (existing) { touchedEnt.add(existing.entity); }
      else {
        const id = newId('ent');
        synthEnts.push({ id, name: p.name, description: p.description || '' });
        synthNames.push({ id: newId('nam'), text: p.name, entity: id });
      }
    } else if (op.kind === 'upsert_statement') {
      const id = newId('stm');
      synthStmts.push({ id, kind: p.kind || 'claim', text: p.text || '', mentions: [] });
      for (const m of (p.mentions || [])) {
        touchedEnt.add(m);
        (synthMentionsByStm[id] = synthMentionsByStm[id] || []).push(m);
      }
      for (const l of (p.links || [])) {
        touchedStm.add(l.to_id);
        synthLinks.push({ from: id, to: l.to_id, link_type: l.link_type });
      }
    } else if (op.kind === 'delete_entity') {
      touchedEnt.add(p.id);
    } else if (op.kind === 'delete_statement') {
      touchedStm.add(p.id);
    } else if (op.kind === 'merge_entities') {
      if (p.source_id) touchedEnt.add(p.source_id);
      if (p.target_id) touchedEnt.add(p.target_id);
    } else if (op.kind === 'add_links' || op.kind === 'remove_links') {
      for (const l of (p.links || [])) {
        if (l.from_id?.startsWith('ent_')) touchedEnt.add(l.from_id);
        else if (l.from_id) touchedStm.add(l.from_id);
        if (l.to_id?.startsWith('ent_')) touchedEnt.add(l.to_id);
        else if (l.to_id) touchedStm.add(l.to_id);
        synthLinks.push({ from: l.from_id, to: l.to_id, link_type: l.link_type });
      }
    } else if (op.kind === 'add_entity_links' || op.kind === 'remove_entity_links') {
      for (const l of (p.links || [])) {
        touchedEnt.add(l.from_id);
        touchedEnt.add(l.to_id);
        synthEntLinks.push({ from: l.from_id, to: l.to_id, link_type: l.link_type });
      }
    }
  }

  // Pull in one-hop substrate neighbors for context.
  const scopedEnt = new Set(touchedEnt);
  const scopedStm = new Set(touchedStm);
  for (const link of (full.entity_links || [])) {
    if (touchedEnt.has(link.from)) scopedEnt.add(link.to);
    if (touchedEnt.has(link.to)) scopedEnt.add(link.from);
  }
  for (const link of (full.links || [])) {
    if (touchedStm.has(link.from)) scopedStm.add(link.to);
    if (touchedStm.has(link.to)) scopedStm.add(link.from);
  }
  for (const s of (full.statements || [])) {
    if (touchedStm.has(s.id)) for (const e of (s.mentions || [])) scopedEnt.add(e);
    for (const e of (s.mentions || [])) if (touchedEnt.has(e)) scopedStm.add(s.id);
  }

  // Materialize the scoped dataset in the same shape as /api/data.
  const entities = [
    ...[...scopedEnt].filter(id => ents.has(id)).map(id => ents.get(id)),
    ...synthEnts,
  ];
  const statements = [
    ...[...scopedStm].filter(id => stmts.has(id)).map(id => ({
      ...stmts.get(id),
      mentions: (stmts.get(id).mentions || []).filter(e => scopedEnt.has(e)),
    })),
    ...synthStmts.map(s => ({ ...s, mentions: synthMentionsByStm[s.id] || [] })),
  ];
  const names = [
    ...(full.names || []).filter(n => scopedEnt.has(n.entity)),
    ...synthNames,
  ];
  const links = [
    ...(full.links || []).filter(l => scopedStm.has(l.from) && scopedStm.has(l.to)),
    ...synthLinks.filter(l =>
      (scopedStm.has(l.from) || synthStmts.some(s => s.id === l.from))
      && (scopedStm.has(l.to) || synthStmts.some(s => s.id === l.to))
    ),
  ];
  const entity_links = [
    ...(full.entity_links || []).filter(l => scopedEnt.has(l.from) && scopedEnt.has(l.to)),
    ...synthEntLinks,
  ];

  return { entities, statements, names, links, entity_links };
}


// Both dimensions scale per size. Widths use `maxWidth` so on a narrow
// viewport the graph still shrinks gracefully; on a wide one L uses
// nearly all available horizontal space.
const _DRAFT_GRAPH_SIZES = {
  S: { label: 'S', height: 380, maxWidth: 760 },
  M: { label: 'M', height: 600, maxWidth: 1180 },
  L: { label: 'L', height: 820, maxWidth: 1720 },
};


function DraftGraph({ ops }) {
  const fullData = window.MYCELIUM_DATA || {};
  const scoped = useMD(() => _buildScopedSubstrate(ops || [], fullData), [ops, fullData]);
  const scopedIndex = useMD(() => window.buildIndex(scoped), [scoped]);
  // Size persists in localStorage so the curator's choice survives a
  // reload — small annoyance to re-pick every time otherwise.
  const [size, setSize] = useD(() => localStorage.getItem('myc_draft_graph_size') || 'M');
  React.useEffect(() => { localStorage.setItem('myc_draft_graph_size', size); }, [size]);

  if (scoped.entities.length + scoped.statements.length === 0) {
    return <div style={{ fontSize: 12, color: 'var(--ink-3)', fontStyle: 'italic', padding: '12px 0' }}>
      No nodes to graph yet.
    </div>;
  }

  const { height, maxWidth } = _DRAFT_GRAPH_SIZES[size];

  // GraphView's `embedded` mode drops the 320px sidepanel and stretches
  // to the parent's height. Without it, GraphView sizes itself to
  // `100vh - 72px`, which renders off the bottom of this card.
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 4, marginBottom: 6 }}>
        {Object.entries(_DRAFT_GRAPH_SIZES).map(([k, v]) => (
          <button
            key={k}
            onClick={() => setSize(k)}
            title={`Resize graph (max ${v.maxWidth}×${v.height}px)`}
            style={{
              fontSize: 11, padding: '2px 8px',
              fontFamily: 'var(--mono)',
              background: size === k ? 'var(--accent, #2563eb)' : 'var(--surface-2)',
              color: size === k ? '#fff' : 'var(--ink-3)',
              border: '1px solid var(--rule)',
              borderRadius: 3, cursor: 'pointer',
            }}
          >{v.label}</button>
        ))}
      </div>
      <div style={{
        height, maxWidth, width: '100%', marginLeft: 'auto', marginRight: 'auto',
        border: '1px solid var(--rule)', borderRadius: 6, overflow: 'hidden',
      }}>
        <GraphView data={scoped} index={scopedIndex} embedded={true} />
      </div>
    </div>
  );
}


function DraftStatusBadge({ status }) {
  const styles = {
    open:      { bg: 'rgba(217,119,6,0.16)', fg: '#d97706' },
    submitted: { bg: 'rgba(37,99,235,0.16)', fg: '#2563eb' },
    approved:  { bg: 'rgba(22,163,74,0.16)', fg: '#16a34a' },
    rejected:  { bg: 'rgba(220,38,38,0.16)', fg: '#dc2626' },
    withdrawn: { bg: 'rgba(107,114,128,0.18)', fg: 'var(--ink-3)' },
  };
  const s = styles[status] || styles.open;
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 4,
      fontFamily: 'var(--mono)', fontSize: 10.5, fontWeight: 600,
      letterSpacing: '0.04em', textTransform: 'uppercase',
      background: s.bg, color: s.fg,
    }}>{status}</span>
  );
}


function DraftRow({ draft, onOpen }) {
  const when = (draft.created_at || '').slice(0, 16).replace('T', ' ');
  const author = (draft.created_by || '').slice(0, 8) || '—';
  return (
    <li style={{
      listStyle: 'none', padding: '12px 14px', borderRadius: 6,
      background: 'var(--surface)', border: '1px solid var(--rule)',
      marginBottom: 8, cursor: 'pointer',
    }} onClick={() => onOpen(draft.id)}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 13, fontFamily: 'var(--mono)' }}>{draft.id}</div>
          <div style={{ fontSize: 11.5, color: 'var(--ink-3)', marginTop: 4, fontFamily: 'var(--mono)' }}>
            {draft.op_count} op{draft.op_count === 1 ? '' : 's'} · filed {when} by {author}
          </div>
        </div>
        <DraftStatusBadge status={draft.status} />
      </div>
    </li>
  );
}


function OpRow({ op, busy, onRemove, onSave, editable }) {
  const [editing, setEditing] = useD(false);
  const [draft, setDraft] = useD(() => JSON.stringify(op.payload || {}, null, 2));
  const [parseErr, setParseErr] = useD(null);

  const startEdit = () => {
    setDraft(JSON.stringify(op.payload || {}, null, 2));
    setParseErr(null);
    setEditing(true);
  };

  const save = async () => {
    let parsed;
    try {
      parsed = JSON.parse(draft);
    } catch (e) {
      setParseErr(e.message);
      return;
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      setParseErr('payload must be a JSON object');
      return;
    }
    setParseErr(null);
    await onSave(op.seq, parsed);
    setEditing(false);
  };

  const payload = op.payload || {};
  // Batch tools (upsert_statements, add_links, ...) carry a list in one
  // of their payload fields. Surface that prominently in the header so
  // a row showing "upsert_statements" doesn't hide the fact that it'll
  // create 24 statements. Scalar fields render as inline summary.
  const arrayFields = Object.entries(payload).filter(([, v]) => Array.isArray(v));
  const scalarSummary = Object.entries(payload)
    .filter(([, v]) => !Array.isArray(v))
    .map(([k, v]) => `${k}=${JSON.stringify(v).slice(0, 80)}`)
    .join(' · ');
  const batchTotal = arrayFields.reduce((n, [, v]) => n + v.length, 0);

  return (
    <li style={{
      listStyle: 'none', padding: '10px 12px', border: '1px solid var(--rule)',
      borderRadius: 4, marginBottom: 6, background: 'var(--surface)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontFamily: 'var(--mono)', color: 'var(--ink-2)' }}>
            <span style={{ color: 'var(--ink-3)' }}>#{op.seq}</span>{' '}
            <strong style={{ color: 'var(--ink)' }}>{op.kind}</strong>
            {batchTotal > 0 && (
              <span style={{
                marginLeft: 8, padding: '1px 7px', borderRadius: 3,
                fontSize: 10.5, fontWeight: 600,
                background: 'rgba(37,99,235,0.14)', color: '#2563eb',
                textTransform: 'uppercase', letterSpacing: '0.04em',
              }}>batch · {batchTotal}</span>
            )}
          </div>
          {!editing && (
            <div style={{
              fontSize: 11.5, color: 'var(--ink-3)', marginTop: 4, fontFamily: 'var(--mono)',
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            }}>
              {arrayFields.map(([k, v]) => (
                <div key={k} style={{ marginBottom: 4 }}>
                  <span style={{ color: 'var(--ink-2)' }}>{k}</span>{' '}
                  <span style={{ color: 'var(--ink-3)' }}>· {v.length} item{v.length === 1 ? '' : 's'}</span>
                  {v.length > 0 && (
                    <ul style={{ margin: '4px 0 0 14px', padding: 0, color: 'var(--ink-3)' }}>
                      {v.slice(0, 5).map((item, i) => (
                        <li key={i} style={{ listStyle: 'disc', fontSize: 11, marginBottom: 2 }}>
                          {typeof item === 'object' && item !== null
                            ? Object.entries(item).slice(0, 3).map(([ik, iv]) =>
                                `${ik}=${typeof iv === 'string' ? JSON.stringify(iv).slice(0, 50) : JSON.stringify(iv).slice(0, 40)}`
                              ).join(' · ')
                            : JSON.stringify(item).slice(0, 80)}
                        </li>
                      ))}
                      {v.length > 5 && (
                        <li style={{ listStyle: 'none', fontSize: 11, fontStyle: 'italic' }}>
                          … {v.length - 5} more
                        </li>
                      )}
                    </ul>
                  )}
                </div>
              ))}
              {scalarSummary && <div>{scalarSummary}</div>}
              {!arrayFields.length && !scalarSummary && '(no args)'}
            </div>
          )}
        </div>
        {editable && !editing && (
          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={startEdit} disabled={busy} style={{ fontSize: 11, padding: '3px 8px' }}
                    title="Edit this op's payload as JSON.">Edit</button>
            <button onClick={() => onRemove(op.seq)} disabled={busy}
                    style={{ fontSize: 11, padding: '3px 8px' }}
                    title="Drop this op from the draft.">Remove</button>
          </div>
        )}
      </div>
      {editing && (
        <div style={{ marginTop: 8 }}>
          <textarea
            value={draft}
            onChange={(e) => { setDraft(e.target.value); setParseErr(null); }}
            spellCheck={false}
            style={{
              width: '100%', minHeight: 140, fontFamily: 'var(--mono)', fontSize: 11.5,
              padding: 8, background: 'var(--surface-2)', border: '1px solid var(--rule)',
              borderRadius: 4, color: 'var(--ink)', resize: 'vertical',
            }}
          />
          {parseErr && <div style={{ color: 'var(--red, #dc2626)', fontSize: 11, marginTop: 4 }}>{parseErr}</div>}
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <button onClick={save} disabled={busy} style={{ fontSize: 11, padding: '3px 10px' }}>Save</button>
            <button onClick={() => setEditing(false)} disabled={busy} style={{ fontSize: 11, padding: '3px 10px' }}>Cancel</button>
          </div>
        </div>
      )}
    </li>
  );
}


function DraftDetail({ draftId, onBack }) {
  const [data, setData] = useD(null);
  const [err, setErr] = useD(null);
  const [busy, setBusy] = useD(false);

  const reload = useCBD(async () => {
    setErr(null);
    try {
      const d = await _fetchDraftDetail(draftId);
      setData(d.draft);
    } catch (e) {
      setErr(e.message);
    }
  }, [draftId]);

  useED(() => { reload(); }, [reload]);

  const act = async (action) => {
    if (action === 'approve' && !confirm('Replay this draft against the substrate?')) return;
    if (action === 'reject' && !confirm('Reject this draft? Ops will not be applied.')) return;
    if (action === 'withdraw' && !confirm('Withdraw this draft? Ops will not be applied and the draft is closed.')) return;
    setBusy(true); setErr(null);
    try {
      await _draftAction(draftId, action);
      await reload();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const removeOp = async (seq) => {
    setBusy(true); setErr(null);
    try {
      await _removeOp(draftId, seq);
      await reload();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const saveOp = async (seq, payload) => {
    setBusy(true); setErr(null);
    try {
      await _editOp(draftId, seq, payload);
      await reload();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!data) {
    return (
      <main className="page"><div className="page-inner" style={{ maxWidth: 880, padding: '32px 24px' }}>
        {err ? <div style={{ color: 'var(--red, #dc2626)', fontSize: 13 }}>{err}</div>
             : <div style={{ color: 'var(--ink-3)', fontSize: 13 }}>loading…</div>}
      </div></main>
    );
  }

  const editable = data.status === 'open' || data.status === 'submitted';
  const canDecide = data.status === 'open' || data.status === 'submitted';

  // Two-tier width: header / actions / ops stay at the readable 880px
  // column the rest of the app uses; the graph card spans much wider
  // (1480px max, viewport-capped) so the canvas has room to breathe
  // even with a 320px+ side toolbar overlay.
  const NARROW = 880;
  // WIDE accommodates the largest graph size (1720px) plus the 24px
  // horizontal padding on each side. The graph card itself caps at the
  // size-derived maxWidth and centers within this container, so smaller
  // sizes still look balanced rather than left-aligned in dead space.
  const WIDE = 1768;
  return (
    <main className="page">
      <div className="page-inner" style={{ maxWidth: NARROW, padding: '32px 24px 0' }}>
        <button onClick={onBack} style={{ fontSize: 12, marginBottom: 14 }}>← all drafts</button>

        <header style={{ marginBottom: 18, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontFamily: 'var(--mono)', fontSize: 18 }}>{data.id}</h1>
            <div style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 4, fontFamily: 'var(--mono)' }}>
              {(data.ops || []).length} op{(data.ops || []).length === 1 ? '' : 's'}
              {' · '}created {(data.created_at || '').slice(0, 16).replace('T', ' ')}
              {' by '}{(data.created_by || '').slice(0, 8) || '—'}
            </div>
          </div>
          <DraftStatusBadge status={data.status} />
        </header>

        {err && <div style={{ color: 'var(--red, #dc2626)', fontSize: 13, marginBottom: 12 }}>{err}</div>}

        {canDecide && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 18 }}>
            <button onClick={() => act('approve')} disabled={busy}
                    style={{ padding: '6px 14px', fontSize: 12 }}
                    title="Replay all ops against the substrate.">Approve</button>
            <button onClick={() => act('reject')} disabled={busy}
                    style={{ padding: '6px 14px', fontSize: 12 }}
                    title="Reject — substrate unchanged.">Reject</button>
            {data.status === 'submitted' && (
              <button onClick={() => act('withdraw')} disabled={busy}
                      style={{ padding: '6px 14px', fontSize: 12 }}
                      title="Withdraw — author pulls it back.">Withdraw</button>
            )}
          </div>
        )}
      </div>

      <div style={{ maxWidth: WIDE, margin: '0 auto', padding: '0 24px' }}>
        <h2 style={{ fontSize: 13, color: 'var(--ink-3)', marginBottom: 8, letterSpacing: '0.04em', textTransform: 'uppercase' }}>Graph</h2>
        <p style={{ fontSize: 11.5, color: 'var(--ink-3)', marginTop: 0, marginBottom: 10 }}>
          Shows the entities and statements the draft touches, plus one hop of substrate context.
          Same controls as the main graph — pan, zoom, drag nodes, click to focus.
        </p>
        <div style={{ marginBottom: 18 }}>
          <DraftGraph ops={data.ops || []} />
        </div>
      </div>

      <div className="page-inner" style={{ maxWidth: NARROW, padding: '0 24px 80px' }}>
        <h2 style={{ fontSize: 13, color: 'var(--ink-3)', marginBottom: 8, letterSpacing: '0.04em', textTransform: 'uppercase' }}>Queued ops</h2>
        <ul style={{ padding: 0, margin: 0 }}>
          {(data.ops || []).map(op => (
            <OpRow key={op.seq} op={op} busy={busy} onRemove={removeOp} onSave={saveOp} editable={editable} />
          ))}
          {(data.ops || []).length === 0 && (
            <li style={{ listStyle: 'none', color: 'var(--ink-3)', fontStyle: 'italic', fontSize: 13 }}>
              No ops queued.
            </li>
          )}
        </ul>
      </div>
    </main>
  );
}


function DraftsScreen({ selected }) {
  const router = React.useContext(window.RouterCtx);
  const [filter, setFilter] = useD('open');
  const [drafts, setDrafts] = useD([]);
  const [err, setErr] = useD(null);
  const [loading, setLoading] = useD(true);

  const reload = useCBD(async (statusFilter) => {
    setLoading(true); setErr(null);
    try {
      const data = await _fetchDrafts(statusFilter);
      setDrafts(data.drafts || []);
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useED(() => {
    if (!selected) reload(filter);
  }, [filter, reload, selected]);

  if (selected) {
    return <DraftDetail draftId={selected} onBack={() => router.go({ view: 'drafts' })} />;
  }

  const FILTERS = [
    { id: 'open', label: 'Open' },
    { id: 'submitted', label: 'Submitted' },
    { id: 'approved', label: 'Approved' },
    { id: 'rejected', label: 'Rejected' },
    { id: 'all', label: 'All' },
  ];

  return (
    <main className="page">
      <div className="page-inner" style={{ maxWidth: 880, padding: '32px 24px 80px' }}>
        <header style={{ marginBottom: 18 }}>
          <h1 style={{ margin: 0 }}>Drafts</h1>
          <p style={{ marginTop: 6, color: 'var(--ink-3)', fontSize: 13 }}>
            Pending change sets from drafter agents. Review the queued ops; approve to replay against the substrate, reject to drop them.
          </p>
        </header>

        <div style={{ display: 'flex', gap: 4, marginBottom: 18, borderBottom: '1px solid var(--rule)' }}>
          {FILTERS.map(f => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              style={{
                padding: '8px 14px', fontSize: 13, border: 'none',
                background: 'transparent', cursor: 'pointer',
                color: filter === f.id ? 'var(--ink)' : 'var(--ink-3)',
                borderBottom: filter === f.id ? '2px solid var(--accent, #2563eb)' : '2px solid transparent',
                marginBottom: -1,
              }}
            >{f.label}</button>
          ))}
        </div>

        {err && <div style={{ color: 'var(--red, #dc2626)', fontSize: 13, marginBottom: 12 }}>{err}</div>}

        {loading ? (
          <div style={{ color: 'var(--ink-3)', fontSize: 13 }}>loading…</div>
        ) : drafts.length === 0 ? (
          <div style={{ color: 'var(--ink-3)', fontSize: 13, fontStyle: 'italic' }}>
            No {filter} drafts.
          </div>
        ) : (
          <ul style={{ padding: 0, margin: 0 }}>
            {drafts.map(d => (
              <DraftRow key={d.id} draft={d} onOpen={(id) => router.go({ view: 'drafts', selected: id })} />
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}


window.DraftsScreen = DraftsScreen;
