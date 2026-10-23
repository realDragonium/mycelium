// Statement and entity detail: where provenance links and graph clicks land.
import { Fragment, useCallback, useState, type FormEvent, type MouseEvent } from 'react';
import { EditableStatementText, EmptyState, EntityChip, I, KindTag, LoadError, Loading, Notice, PageHeader, formatDate, useDataCtx, useMe } from './lib';
import { Link, useRouter } from './router';
import { deleteJSON, enc, errorMessage, getJSON, isScoped, putJSON, upsertEntity, upsertName } from './api';
import { substrate, type Entity, type EntityLink, type Link as SubstrateLink, type Statement, type SubstrateIndex, type When } from './data';
import { AudienceIdentity, TextChangedActions, type AudienceLabel, type AudienceRef } from './audiences';
import { useAsync } from './use-async';

/* ============================ when-conditions ============================ */
// A when-tree as one line: leaves are statement titles, groups use AND / OR.
// Older substrates emitted a flat statement-id string.
function whenText(when: When): string {
  const idx = substrate.index;
  if (typeof when === 'string') return idx.statements[when]?.title || when;
  if ('statement_id' in when) return idx.statements[when.statement_id]?.title || when.statement_id;
  const sep = when.op === 'and' ? ' AND ' : when.op === 'or' ? ' OR ' : ` ${when.op.toUpperCase()} `;
  const inner = when.of.map(whenText).join(sep);
  return when.op === 'not' ? `NOT (${inner})` : `(${inner})`;
}

// The single statement a leaf condition points at; composite trees have none.
function whenLeafId(when: When): string | null {
  if (typeof when === 'string') return when;
  return 'statement_id' in when ? when.statement_id : null;
}

// A when-tree as nested blocks: each group labelled, its children stacked.
function WhenTree({ when }: { when: When }) {
  const idx = substrate.index;
  if (typeof when === 'string' || 'statement_id' in when) {
    const id = typeof when === 'string' ? when : when.statement_id;
    return <span className="leaf">{idx.statements[id]?.title || id}</span>;
  }
  const label = when.op === 'and' ? 'all of these must hold:' : when.op === 'or' ? 'at least one of these must hold:' : 'this must not hold:';
  return (
    <div className={`grp grp-${when.op}`}>
      <div className="op-label">{label}</div>
      <div className="grp-children">{when.of.map((c, i) => <div key={i} className="grp-child"><WhenTree when={c} /></div>)}</div>
    </div>
  );
}

/* ============================ connections ============================ */
interface Conn { link: SubstrateLink; target: Statement; type: string; primary: boolean }

// The chain of `type` links leading into `id`, root first, excluding `id`.
function lineage(id: string, idx: SubstrateIndex, type: string, maxDepth = 6): Statement[] {
  const out: Statement[] = [];
  const seen = new Set([id]);
  let cur = id;
  for (let i = 0; i < maxDepth; i++) {
    const next = (idx.incoming[cur] || []).find(l => l.link_type === type)?.from;
    if (!next || seen.has(next) || !idx.statements[next]) break;
    seen.add(next);
    out.unshift(idx.statements[next]);
    cur = next;
  }
  return out;
}

function Peek({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const toggle = (e: MouseEvent) => { e.preventDefault(); e.stopPropagation(); setOpen(o => !o); };
  return <>
    <button type="button" className="peek-btn" title="Show the full text" aria-expanded={open} onClick={toggle}>⌖</button>
    {open && <div className="peek-pop" onClick={e => { e.preventDefault(); e.stopPropagation(); }}>{text}</div>}
  </>;
}

type Tip = { x: number; y: number; when: When | null };

function ConnectionsGraph({ incoming, outgoing, center }: { incoming: Conn[]; outgoing: Conn[]; center: Statement }) {
  const [tip, setTip] = useState<Tip | null>(null);
  // The canvas grows with the busier side so each node keeps a fixed slot.
  const W = 1100, STEP = 96, TOP = 70, BOTTOM = 50;
  const H = Math.max(380, TOP + BOTTOM + STEP * Math.max(incoming.length, outgoing.length, 1));
  const cx = W / 2, cy = H / 2, inX = 200, outX = W - 200;
  const yFor = (i: number, n: number) => n <= 1 ? cy : cy - STEP * (n - 1) / 2 + STEP * i;
  const pct = (x: number, y: number) => ({ left: `${x / W * 100}%`, top: `${y / H * 100}%` });

  const edge = (c: Conn, i: number, side: 'in' | 'out') => {
    const n = side === 'in' ? incoming.length : outgoing.length;
    const y = yFor(i, n);
    const mid = side === 'in' ? (inX + cx) / 2 : (cx + outX) / 2;
    const d = side === 'in'
      ? `M ${inX + 100},${y} C ${mid},${y} ${mid},${cy} ${cx - 100},${cy}`
      : `M ${cx + 100},${cy} C ${mid},${cy} ${mid},${y} ${outX - 100},${y}`;
    const my = (y + cy) / 2;
    const when = c.link.when ?? null;
    return (
      <g key={side + c.target.id + i} className={`edge lt-${c.type}${c.primary ? ' primary' : ''}${when ? ' has-when' : ''}`}>
        <path d={d} stroke="currentColor" strokeWidth={c.primary ? 1.6 : 0.9} fill="none" opacity={c.primary ? 0.95 : 0.55} strokeDasharray={c.primary ? '' : '3 3'} />
        <text x={mid + (side === 'in' ? 6 : -6)} y={my - 14} fill="currentColor" fontFamily="var(--mono)" fontSize="9.5" opacity={c.primary ? 0.95 : 0.7} textAnchor="middle">{c.type}</text>
        {/* Every edge carries a marker, so "unconditional" is as explicit as "conditional". */}
        <g className={`cond-marker ${when ? 'is-cond' : 'is-none'}`} onMouseEnter={() => setTip({ x: mid, y: my, when })} onMouseLeave={() => setTip(null)}>
          <circle cx={mid} cy={my} r={14} fill="transparent" />
          {when ? <><circle cx={mid} cy={my} r="11" className="halo" /><circle cx={mid} cy={my} r="6" className="bead" /></>
            : <circle cx={mid} cy={my} r="6" className="ring" />}
        </g>
      </g>
    );
  };
  const node = (c: Conn, i: number, side: 'in' | 'out') => (
    <Link key={side + c.target.id + i} to={{ view: 'statement', id: c.target.id }} className={`node ${side === 'in' ? 'parent' : 'child'}${c.primary ? ' primary' : ' secondary'}`}
      style={pct(side === 'in' ? inX : outX, yFor(i, side === 'in' ? incoming.length : outgoing.length))}>
      <span className="nlabel">
        <span className={`lt lt-${c.type}`}>{c.type}</span>
        <span className="ntext">{c.target.title || c.target.text}</span>
        <span className="nid">{c.target.id}</span>
        <Peek text={c.target.text} />
      </span>
    </Link>
  );

  return (
    <div className="conn-canvas" style={{ height: H }}>
      <svg className="edges" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
        <defs>
          <pattern id="conn-grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--line-soft)" strokeWidth="1" /></pattern>
          <radialGradient id="conn-glow" cx="50%" cy="50%" r="50%"><stop offset="0%" stopColor="var(--bio)" stopOpacity="0.16" /><stop offset="100%" stopColor="var(--bio)" stopOpacity="0" /></radialGradient>
        </defs>
        <rect width="100%" height="100%" fill="url(#conn-grid)" opacity="0.5" />
        <circle cx={cx} cy={cy} r="180" fill="url(#conn-glow)" />
        {incoming.map((c, i) => edge(c, i, 'in'))}
        {outgoing.map((c, i) => edge(c, i, 'out'))}
      </svg>
      {tip && (
        <div className={`cond-tooltip ${tip.when ? 'is-cond' : 'is-none'}`} style={pct(tip.x, tip.y)}>
          {tip.when
            ? <><div className="head">⚡ conditional</div><div className="sub">fires only when:</div><div className="tree"><WhenTree when={tip.when} /></div></>
            : <><div className="head">no condition</div><div className="sub">this link always applies</div></>}
        </div>
      )}
      <span className="col-label" style={{ left: `${inX / W * 100}%` }}>↑ incoming · {incoming.length}</span>
      <span className="col-label accent" style={{ left: '50%' }}>▣ this statement</span>
      <span className="col-label accent" style={{ left: `${outX / W * 100}%` }}>↓ outgoing · {outgoing.length}</span>
      {incoming.length === 0 && <div className="empty-side" style={pct(inX, cy)}>no incoming links<br />under this filter</div>}
      {outgoing.length === 0 && <div className="empty-side" style={pct(outX, cy)}>no outgoing links<br />under this filter</div>}
      {incoming.map((c, i) => node(c, i, 'in'))}
      <div className="node center" style={pct(cx, cy)}><span className="nlabel"><span className="ntext">{center.title}</span><span className="nid">{center.id}</span></span></div>
      {outgoing.map((c, i) => node(c, i, 'out'))}
    </div>
  );
}

function ConnectionsList({ incoming, outgoing }: { incoming: Conn[]; outgoing: Conn[] }) {
  const { go } = useRouter();
  const column = (items: Conn[], dir: 'in' | 'out') => {
    const groups = new Map<string, Conn[]>();
    items.forEach(c => groups.set(c.type, [...(groups.get(c.type) || []), c]));
    return (
      <div className={`conn-col ${dir}`}>
        <h4><span>{dir === 'in' ? '↑ incoming' : '↓ outgoing'}</span><span className="ct">{items.length}</span></h4>
        {items.length === 0 && <div className="muted mono small">none under this filter</div>}
        {[...groups.entries()].map(([type, list]) => (
          <div key={type} className={`type-group${list[0].primary ? ' primary' : ''}`}>
            <div className="type-group-head"><span className={`lt lt-${type}`}>{type}</span>{list[0].primary && <span className="prim-flag">▣ primary</span>}<span className="ct">{list.length}</span></div>
            {list.map((c, i) => {
              const leaf = c.link.when ? whenLeafId(c.link.when) : null;
              return (
                <div key={c.target.id + i} className={`item${c.primary ? '' : ' secondary'}`}>
                  <Link to={{ view: 'statement', id: c.target.id }} className="item-main">
                    <span className={`when-badge${c.link.when ? '' : ' none'}`}>{c.link.when ? '⚡ conditional' : 'no condition'}</span>
                    <span>{c.target.title || c.target.text}</span>
                    <span className="iid">{c.target.id}</span>
                  </Link>
                  {c.link.when && (
                    <button className="when-line" disabled={!leaf || !substrate.index.statements[leaf]} onClick={() => leaf && go({ view: 'statement', id: leaf })}>
                      ↳ when: {whenText(c.link.when)}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    );
  };
  return <div className="conn-list">{column(incoming, 'in')}{column(outgoing, 'out')}</div>;
}

function Connections({ statement }: { statement: Statement }) {
  const idx = substrate.index;
  const id = statement.id;
  const allOut = (idx.outgoing[id] || []).filter(l => idx.statements[l.to]);
  const allIn = (idx.incoming[id] || []).filter(l => idx.statements[l.from]);
  const typeCounts: Record<string, number> = {};
  [...allOut, ...allIn].forEach(l => { typeCounts[l.link_type] = (typeCounts[l.link_type] || 0) + 1; });
  // `contains` is the structural anchor when present; otherwise the most used type.
  const types = Object.keys(typeCounts).sort((a, b) => (a === 'contains' ? -1 : b === 'contains' ? 1 : typeCounts[b] - typeCounts[a] || a.localeCompare(b)));
  const primary = types[0] || 'contains';
  const [mode, setMode] = useState<'graph' | 'list'>('graph');
  // null shows every type; a filter is reset when another statement opens.
  const [filter, setFilter] = useState<{ id: string; types: Set<string> } | null>(null);
  const active = filter && filter.id === id ? filter.types : new Set(types);
  const toggle = (t: string, only: boolean) => {
    const next = only ? new Set([t]) : new Set(active);
    if (!only) { if (next.has(t)) next.delete(t); else next.add(t); }
    setFilter({ id, types: next });
  };
  const toConn = (l: SubstrateLink, dir: 'in' | 'out'): Conn => ({ link: l, target: idx.statements[dir === 'in' ? l.from : l.to], type: l.link_type, primary: l.link_type === primary });
  const sort = (list: Conn[]) => list.sort((x, y) => (x.primary !== y.primary ? (x.primary ? -1 : 1) : x.type.localeCompare(y.type) || (x.target.title || '').localeCompare(y.target.title || '')));
  const incoming = sort(allIn.filter(l => active.has(l.link_type)).map(l => toConn(l, 'in')));
  const outgoing = sort(allOut.filter(l => active.has(l.link_type)).map(l => toConn(l, 'out')));
  const uses = idx.conditionUses[id] || [];

  return (
    <section className="card conn-card" aria-label="Connections">
      <header className="conn-head">
        <h2 className="section-label">Connections <span className="ct">{allIn.length + allOut.length}</span></h2>
        <span className="legend">primary type drawn strongest · <span className="legend-cond" /> conditional · <span className="legend-none" /> no condition</span>
        <div className="seg" role="group" aria-label="Connections view">
          <button className={mode === 'graph' ? 'on' : ''} aria-pressed={mode === 'graph'} onClick={() => setMode('graph')}>graph</button>
          <button className={mode === 'list' ? 'on' : ''} aria-pressed={mode === 'list'} onClick={() => setMode('list')}>list</button>
        </div>
      </header>
      {types.length > 0 && (
        <div className="filter-row compact" role="group" aria-label="Link types">
          <span className="ll">types</span>
          {types.map(t => (
            <button key={t} className={`type-chip lt-${t}${active.has(t) ? ' on' : ''}${t === primary ? ' primary' : ''}`} aria-pressed={active.has(t)}
              title="click: only this type · shift-click: toggle"
              onClick={e => toggle(t, !e.shiftKey && !(active.has(t) && active.size === 1))}>
              {t === primary && <span className="prim-dot">▣</span>}{t}<span className="t-ct">{typeCounts[t]}</span>
            </button>
          ))}
          {types.length > 1 && <button className={`type-chip all${active.size === types.length ? ' on' : ''}`} onClick={() => setFilter(null)}>all</button>}
        </div>
      )}
      {allIn.length + allOut.length === 0
        ? <p className="muted mono small pad">No statement connections: this statement stands alone.</p>
        : mode === 'graph' ? <ConnectionsGraph incoming={incoming} outgoing={outgoing} center={statement} /> : <ConnectionsList incoming={incoming} outgoing={outgoing} />}
      {uses.length > 0 && (
        <div className="cond-uses">
          <h3 className="section-label">⚡ Gates {uses.length} edge{uses.length === 1 ? '' : 's'}</h3>
          <p className="muted small">This statement is a <code>when</code> condition: these edges apply only while it holds.</p>
          <ul>{uses.map((l, i) => (
            <li key={i}><Link to={{ view: 'statement', id: l.from }}>
              <span>{idx.statements[l.from]?.title || l.from}</span><span className="lt">{l.link_type}</span><span>{idx.statements[l.to]?.title || l.to}</span>
            </Link></li>
          ))}</ul>
        </div>
      )}
    </section>
  );
}

/* ============================ add a mention ============================ */
// Mentions are derived, not asserted: attach an alias to an entity or create
// one, and the matcher links every statement containing the name on its next
// scan. The new link appears after a reload, hence the explicit button.
function AddMention() {
  const { refresh } = useDataCtx();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<'existing' | 'new'>('existing');
  const [query, setQuery] = useState('');
  const [entity, setEntity] = useState<Entity | null>(null);
  const [alias, setAlias] = useState('');
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const idx = substrate.index;
  const q = query.trim().toLowerCase();
  const matches = !q ? [] : substrate.data.entities.filter(e =>
    e.name.toLowerCase().includes(q) || (idx.namesByEntity[e.id] || []).some(n => n.text.toLowerCase().includes(q))).slice(0, 8);
  const canSubmit = mode === 'existing' ? !!(entity && alias.trim()) : !!name.trim();
  const reset = () => { setQuery(''); setEntity(null); setAlias(''); setName(''); setDesc(''); setErr(null); };

  const submit = async () => {
    if (!canSubmit || busy) return;
    setBusy(true); setErr(null);
    const label = mode === 'existing' ? alias.trim() : name.trim();
    try {
      if (mode === 'existing' && entity) await upsertName(label, entity.id);
      else await upsertEntity(label, desc.trim());
      reset(); setOpen(false); setDone(label);
    } catch (e) { setErr(errorMessage(e, 'Could not add that.')); }
    finally { setBusy(false); }
  };

  if (done) {
    return (
      <div className="notice success">
        <I.check width="15" height="15" />
        <span>Added <b>“{done}”</b>. The matcher links it to every statement containing it on its next scan.</span>
        <span className="spacer" />
        <button className="btn sm" onClick={() => void refresh()}>Reload data</button>
        <button className="btn ghost sm" onClick={() => { setDone(null); setOpen(true); }}>Add another</button>
      </div>
    );
  }
  if (!open) return <button className="btn ghost sm" onClick={() => { reset(); setOpen(true); }}>+ add mention</button>;
  return (
    <div className="card add-mention">
      <div className="filter-row compact">
        <span className="ll">map to</span>
        <button className={`fchip${mode === 'existing' ? ' on' : ''}`} aria-pressed={mode === 'existing'} onClick={() => setMode('existing')}>existing entity</button>
        <button className={`fchip${mode === 'new' ? ' on' : ''}`} aria-pressed={mode === 'new'} onClick={() => setMode('new')}>new entity</button>
        <span className="spacer" />
        <button className="btn ghost sm" onClick={() => { setOpen(false); reset(); }}>Cancel</button>
      </div>
      {mode === 'existing' ? (
        !entity ? <>
          <input className="input" autoFocus value={query} placeholder="Search entities by name or alias…" aria-label="Search entities" spellCheck={false} onChange={e => setQuery(e.target.value)} />
          {q && <div className="pick-list">
            {matches.length === 0
              ? <p className="muted mono small">No entity matches. Switch to “new entity” to create one.</p>
              : matches.map(e => <button key={e.id} className="pick-item" onClick={() => { setEntity(e); setQuery(''); }}><b>{e.name}</b><span className="muted">{e.description}</span></button>)}
          </div>}
        </> : (
          <div className="row gap-sm wrap">
            <span className="ll">alias for</span><EntityChip entity={entity} />
            <button className="btn ghost sm" onClick={() => setEntity(null)}>change</button>
            <input className="input grow" autoFocus value={alias} placeholder="The word as it appears in the text" aria-label="Alias" spellCheck={false}
              onChange={e => setAlias(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') void submit(); }} />
            <button className="btn primary sm" disabled={!canSubmit || busy} onClick={() => void submit()}>Add alias</button>
          </div>
        )
      ) : (
        <div className="stack-sm">
          <input className="input" autoFocus value={name} spellCheck={false} aria-label="Entity name" placeholder="Entity name: a word in this statement gets linked"
            onChange={e => setName(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') void submit(); }} />
          <input className="input" value={desc} spellCheck={false} aria-label="Description" placeholder="Short description (optional)"
            onChange={e => setDesc(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') void submit(); }} />
          <div><button className="btn primary sm" disabled={!canSubmit || busy} onClick={() => void submit()}>Create entity</button></div>
        </div>
      )}
      {err && <p className="form-error" role="alert">{err}</p>}
    </div>
  );
}

/* ============================ statement ============================ */
function CopyId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  return <button className="btn ghost sm" onClick={() => { void navigator.clipboard?.writeText(id); setCopied(true); }}>{copied ? 'Copied' : 'Copy id'}</button>;
}

interface StatementAudience extends AudienceRef { visible: boolean }
interface StatementAudienceData {
  statement_id: string; label: AudienceLabel | null; queued: boolean; audiences: StatementAudience[]; can_curate: boolean;
}

function AudienceCuration({ data, onSaved }: { data: StatementAudienceData; onSaved: (value: StatementAudienceData) => void }) {
  const [selected, setSelected] = useState(() => { const live = new Set(data.audiences.map(audience => audience.id)); return new Set((data.label?.audiences || []).filter(id => live.has(id))); });
  const [reason, setReason] = useState(data.label?.source === 'curator' ? data.label.reason : '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toggle = (id: string) => setSelected(current => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null);
    try { onSaved(await putJSON<StatementAudienceData>(`/api/statements/${enc(data.statement_id)}/audiences`, { audiences: [...selected], reason: reason.trim() })); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  const handBack = async () => {
    setBusy(true); setError(null);
    try { onSaved(await deleteJSON<StatementAudienceData>(`/api/statements/${enc(data.statement_id)}/audiences`)); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <form className="audience-curation" onSubmit={save}><fieldset disabled={busy}>
    <div className="audience-checks">{data.audiences.map(audience => <label key={audience.id} className="check"><input type="checkbox" checked={selected.has(audience.id)} onChange={() => toggle(audience.id)} /><AudienceIdentity audience={audience} /></label>)}</div>
    <label className="field"><span>Override reason</span><input className="input" required maxLength={500} value={reason} onChange={event => setReason(event.target.value)} /></label>
    <div className="row gap-sm wrap"><button type="submit" className="btn primary sm" disabled={!reason.trim()}>{busy ? 'Saving…' : 'Save override'}</button>{data.label?.source === 'curator' && <button type="button" className="btn ghost sm" onClick={() => void handBack()}>Hand back to AI</button>}</div>
  </fieldset>{error && <Notice tone="error">{error}</Notice>}</form>;
}

function StatementAudiences({ id }: { id: string }) {
  const { state, reload, update } = useAsync(useCallback((signal: AbortSignal) => getJSON<StatementAudienceData>(`/api/statements/${enc(id)}/audiences`, signal), [id]));
  return <section className="card statement-audiences" aria-label="Audiences"><h2 className="section-label">Audiences</h2>
    {state.status === 'loading' && <Loading what="statement audiences" />}
    {state.status === 'error' && <LoadError error={state.error} what="statement audiences" onRetry={reload} />}
    {state.status === 'ready' && (() => { const data = state.data; const label = data.label; return <>
      {data.queued && <Notice>Queued for labelling.</Notice>}
      {!label ? <Notice tone="warn">Unlabelled: internal audiences only.</Notice> : <p className="audience-label-summary"><b>{label.source === 'ai' ? `AI${label.model ? ` · ${label.model}` : ''}` : `Curator${label.labelled_by ? ` · ${label.labelled_by}` : ''}`}</b> · {formatDate(label.labelled_at)}<br />{label.reason}</p>}
      {label?.text_changed_at && <Notice tone="warn">Text changed since decision ({formatDate(label.text_changed_at)}). The curator label still applies until a curator confirms it or hands it back to AI.{data.can_curate && <TextChangedActions statementId={data.statement_id} onDone={reload} />}</Notice>}
      <div className="statement-audience-list">{data.audiences.map(audience => <div key={audience.id}><AudienceIdentity audience={audience} /><span className={`audience-visible ${audience.visible ? 'yes' : 'no'}`}>{audience.visible ? 'Visible' : 'Hidden'}</span></div>)}</div>
      {data.can_curate && <AudienceCuration key={`${label?.labelled_at || 'none'}:${data.queued}`} data={data} onSaved={value => update(() => value)} />}
    </>; })()}
  </section>;
}

export function StatementDetail({ id }: { id: string }) {
  const { go } = useRouter();
  const scoped = isScoped(useMe());
  const [edits, setEdits] = useState(0);
  const idx = substrate.index;
  const s = idx.statements[id];
  if (!s) return <main className="page narrow"><EmptyState title="Statement not found" blurb={`No statement has the id ${id}. It may have been merged or deleted.`}><Link to={{ view: 'browse' }} className="btn">Browse records</Link></EmptyState></main>;

  const out = idx.outgoing[id] || [];
  const inc = idx.incoming[id] || [];
  const mentions = s.mentions.map(eid => idx.entities[eid]).filter((e): e is Entity => !!e);
  const def = substrate.vocab.statementKinds.find(k => k.name === s.kind);
  const chain = lineage(id, idx, 'contains');

  return (
    <main className="page">
      <PageHeader eyebrow={<><Link to={{ view: 'browse' }}>Statements</Link> / <span className="mono">{s.id}</span></>}
        title={<span className="sr-only">Statement {s.id}</span>}
        actions={<>
          <CopyId id={s.id} />
          <Link to={{ view: 'graph', focus: s.id }} className="btn ghost sm"><I.graph width="14" height="14" />View in graph</Link>
          <button className="btn sm ask" onClick={() => go({ view: 'ask', query: `Explain: ${s.title}` })}><I.ask width="14" height="14" />Ask about this</button>
        </>} />

      <div className="inspect-grid">
        <div>
          <header className="stmt-head">
            <div className="stmt-meta"><KindTag kind={s.kind} /><span className="sm-id">{s.id}</span></div>
            <EditableStatementText statement={s} className="stmt-text" onSaved={() => setEdits(n => n + 1)} />
            {chain.length > 0 && (
              <nav className="lineage" aria-label="Contained in">
                <span className="lt lt-contains">contains</span><span className="muted small">chain</span>
                {chain.map(p => <Fragment key={p.id}><Link to={{ view: 'statement', id: p.id }} className="step" title={p.title}>{p.title}</Link><span className="arr">›</span></Fragment>)}
                <span className="here">this</span>
              </nav>
            )}
          </header>

          <section className="sec">
            <div className="sec-head"><span className="sh-title">Mentions · entities</span><span className="sh-count">{mentions.length}</span></div>
            {mentions.length > 0 && <div className="chip-row">{mentions.map(e => <EntityChip key={e.id} entity={e} />)}</div>}
            {!scoped && <AddMention />}
          </section>

          {!scoped && <StatementAudiences key={`${s.id}:${edits}`} id={s.id} />}

          <Connections statement={s} />
        </div>

        <aside className="rail">
          <div className="rail-sec">
            <div className="rs-label">record</div>
            <div className="rail-kv"><span className="k">kind</span><span className="v">{s.kind}</span></div>
            <div className="rail-kv"><span className="k">layer</span><span className="v">{def?.layer || '—'}</span></div>
            <div className="rail-kv"><span className="k">id</span><span className="v">{s.id}</span></div>
          </div>
          <div className="rail-sec">
            <div className="rs-label">degree</div>
            <div className="rail-kv"><span className="k">outgoing</span><span className="v">{out.length}</span></div>
            <div className="rail-kv"><span className="k">incoming</span><span className="v">{inc.length}</span></div>
            <div className="rail-kv"><span className="k">mentions</span><span className="v">{mentions.length}</span></div>
            <div className="rail-kv"><span className="k">conditional edges</span><span className="v">{[...out, ...inc].filter(l => l.when).length}</span></div>
            <div className="rail-kv"><span className="k">gates</span><span className="v">{(idx.conditionUses[id] || []).length}</span></div>
          </div>
          {def?.gloss && (
            <div className="rail-sec">
              <div className="rs-label">about this kind</div>
              <p className="small"><b className="mono">{def.name}</b>: {def.gloss} A <b>{def.layer}</b> kind. <Link to={{ view: 'glossary' }}>Glossary</Link></p>
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}

/* ============================ entity ============================ */
function EntityLinks({ title, links, dir }: { title: string; links: EntityLink[]; dir: 'in' | 'out' }) {
  const idx = substrate.index;
  return (
    <div>
      <div className="col-head">{title} · {links.length}</div>
      {links.length === 0 && <div className="muted mono small">none</div>}
      {links.map((l, i) => {
        const other = idx.entities[dir === 'out' ? l.to : l.from];
        return other && (
          <Link key={i} to={{ view: 'entity', id: other.id }} className="linkline">
            <span className="ll-dir">{dir === 'out' ? '→' : '←'}</span><span className="lt">{l.link_type}</span>
            <span className="ll-target">{other.name}</span><span className="ll-tid">{other.id}</span>
          </Link>
        );
      })}
    </div>
  );
}

export function EntityDetail({ id }: { id: string }) {
  const scoped = isScoped(useMe());
  const idx = substrate.index;
  const e = idx.entities[id];
  if (!e) return <main className="page narrow"><EmptyState title="Entity not found" blurb={`No entity has the id ${id}. It may have been merged or deleted.`}><Link to={{ view: 'browse' }} className="btn">Browse records</Link></EmptyState></main>;

  const aliases = (idx.namesByEntity[id] || []).filter(n => n.text !== e.name);
  const mentionedBy = idx.mentionsByEntity[id] || [];
  const outLinks = idx.entityOutgoing[id] || [];
  const inLinks = idx.entityIncoming[id] || [];

  return (
    <main className="page">
      <PageHeader eyebrow={<><Link to={{ view: 'browse' }}>Entities</Link> / <span className="mono">{e.id}</span></>}
        title={<span className="entity-name">{e.name}</span>}
        blurb={e.description}
        actions={<>
          <Link to={{ view: 'find', query: e.name, mode: 'grep' }} className="btn ghost sm"><I.find width="13" height="13" />Find mentions</Link>
          <Link to={{ view: 'entities', focus: e.id }} className="btn ghost sm"><I.hub width="14" height="14" />Entity map</Link>
          <Link to={{ view: 'graph', focus: e.id }} className="btn ghost sm"><I.graph width="14" height="14" />Statement graph</Link>
        </>} />
      {aliases.length > 0 && <div className="alias-row">{aliases.map(n => <span key={n.id} className="alias">{n.text}</span>)}</div>}

      <div className="inspect-grid">
        <div>
          <section className="sec">
            <div className="sec-head"><span className="sh-title">← mentioned by · statements</span><span className="sh-count">{mentionedBy.length}</span></div>
            {mentionedBy.length === 0 ? <p className="muted mono small pad">No statement mentions this entity.</p>
              : mentionedBy.map(s => (
                <Link key={s.id} to={{ view: 'statement', id: s.id }} className="linkline">
                  <span className="ll-dir">←</span><KindTag kind={s.kind} /><span className="ll-target">{s.title || s.text}</span><span className="ll-tid">{s.id}</span>
                </Link>
              ))}
          </section>
          <section className="sec">
            <div className="sec-head"><span className="sh-title">entity ↔ entity links</span><span className="sh-count">{outLinks.length + inLinks.length}</span></div>
            <div className="two-col">
              <EntityLinks title="outgoing" links={outLinks} dir="out" />
              <EntityLinks title="incoming" links={inLinks} dir="in" />
            </div>
            {!scoped && <p className="hint">Add or remove entity links on the <Link to={{ view: 'entities', focus: e.id }}>entity map</Link>.</p>}
          </section>
        </div>
        <aside className="rail">
          <div className="rail-sec">
            <div className="rs-label">record</div>
            <div className="rail-kv"><span className="k">kind</span><span className="v">entity</span></div>
            <div className="rail-kv"><span className="k">id</span><span className="v">{e.id}</span></div>
          </div>
          <div className="rail-sec">
            <div className="rs-label">reach</div>
            <div className="rail-kv"><span className="k">aliases</span><span className="v">{aliases.length}</span></div>
            <div className="rail-kv"><span className="k">mentioned by</span><span className="v">{mentionedBy.length}</span></div>
            <div className="rail-kv"><span className="k">entity links</span><span className="v">{outLinks.length}↗ {inLinks.length}↙</span></div>
          </div>
          <div className="rail-sec">
            <div className="rs-label">names that resolve here</div>
            <div className="chip-row">{(idx.namesByEntity[id] || []).map(n => <span key={n.id} className="lt">{n.text}</span>)}</div>
            {!scoped && <p className="hint"><Link to={{ view: 'names' }}>Curate names &amp; aliases</Link></p>}
          </div>
        </aside>
      </div>
    </main>
  );
}
