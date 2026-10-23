import { Fragment, useCallback, useEffect, useState, type FormEvent } from 'react';
import { deleteJSON, enc, errorMessage, getJSON, postJSON, putJSON } from './api';
import { Card, KindTag, LoadError, Loading, Notice } from './lib';
import { Link } from './router';
import { dataOf, useAsync } from './use-async';

export type AudienceScope = 'internal' | 'external';
export interface AudienceRef { id: string; name: string; scope: AudienceScope }
export interface AudienceLabel {
  audiences: string[]; source: 'ai' | 'curator'; reason: string; model: string | null;
  labelled_at: string; labelled_by: string | null; text_changed_at: string | null;
}
export interface AudienceView extends AudienceRef {
  description: string; version: number; retired: boolean; default: boolean; profiles: string[];
  visible_statements: number; unlabelled_statements: number;
}
export interface AudienceStatus {
  statements: number; labelled_ai: number; labelled_curator: number; unlabelled: number; queued: number; failed: number;
  last_error: string | null; cost_usd: number; automatic: boolean; model: string; provider: string;
  backfill: BackfillProgress | null;
}
interface Backfill { started_at: string; queued: number }
interface BackfillProgress extends Backfill { labelled: number; cost_usd: number }
export interface AudiencesResponse {
  audiences: AudienceView[]; can_configure: boolean; statements: number; unlabelled: number; labelling: AudienceStatus;
}

interface AudienceStatement {
  id: string; kind: string; text: string; label: AudienceLabel | null; queued: boolean;
}
interface AudienceStatementPage { statements: AudienceStatement[]; total: number; can_curate: boolean }
type Visibility = '' | 'visible' | 'hidden';
type LabelState = '' | 'unlabelled' | 'ai' | 'curator' | 'text_changed' | 'queued';
const LABEL_STATES = ['unlabelled', 'ai', 'curator', 'text_changed', 'queued'] as const;
const isLabelState = (value: string): value is Exclude<LabelState, ''> => (LABEL_STATES as readonly string[]).includes(value);
interface StatementFilter { audience: string; visibility: Visibility; state: LabelState }
interface AudienceDraft { id: string; name: string; scope: AudienceScope; description: string }

export const AudienceBadge = ({ scope }: { scope: AudienceScope }) => <span className={`audience-badge ${scope}`}>{scope}</span>;
export const AudienceIdentity = ({ audience }: { audience: AudienceRef }) => <span className="audience-identity"><span>{audience.name}</span><AudienceBadge scope={audience.scope} /></span>;

const formatCost = (value: number | null) => value === null ? '—' : `$${value.toFixed(value >= 1 ? 2 : 4)}`;
const labelSummary = (label: AudienceLabel | null, queued: boolean) => queued ? 'Queued for labelling' : !label ? 'Unlabelled' : label.source === 'ai' ? `AI${label.model ? ` · ${label.model}` : ''}` : `Curator${label.labelled_by ? ` · ${label.labelled_by}` : ''}${label.text_changed_at ? ' · text changed since decision' : ''}`;

export function TextChangedActions({ statementId, onDone }: { statementId: string; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const act = async (request: Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await request; onDone(); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <div className="row gap-sm wrap audience-text-changed">
    <button type="button" className="btn sm" disabled={busy} onClick={() => void act(postJSON(`/api/statements/${enc(statementId)}/audiences/confirm`))}>Confirm</button>
    <button type="button" className="btn ghost sm" disabled={busy} onClick={() => void act(deleteJSON(`/api/statements/${enc(statementId)}/audiences`))}>Hand back to AI</button>
    {error && <Notice tone="error">{error}</Notice>}
  </div>;
}

function LabellingCard({ data, onReload }: { data: AudiencesResponse; onReload: () => void }) {
  const [polledStatus, setPolledStatus] = useState<AudienceStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const status = polledStatus || data.labelling;
  const running = !!status.backfill && status.queued > 0;
  useEffect(() => {
    if (!running) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await getJSON<AudienceStatus>('/api/audiences/labelling', controller.signal);
        if (controller.signal.aborted) return;
        // A drained queue reports no run; keep the one this page followed.
        setPolledStatus(prev => ({ ...next, backfill: next.backfill ?? prev?.backfill ?? null })); setError(null);
        if (next.queued > 0) timer = setTimeout(poll, 3000);
        else onReload();
      } catch (cause) { if (!controller.signal.aborted) { setError(errorMessage(cause)); timer = setTimeout(poll, 3000); } }
    };
    timer = setTimeout(poll, 3000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [running, onReload]);
  const start = async (relabelAi: boolean) => {
    if (relabelAi && !window.confirm('Relabel every AI-labelled statement? Curator labels are kept.')) return;
    setBusy(true); setError(null);
    try {
      const result = await postJSON<Backfill>('/api/audiences/labelling/backfill', { relabel_ai: relabelAi });
      setPolledStatus({ ...status, queued: result.queued, backfill: { ...result, labelled: 0, cost_usd: 0 } });
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <Card title="Statement labelling" actions={data.can_configure && <><button type="button" className="btn sm" disabled={busy} onClick={() => void start(false)}>Label unlabelled statements</button><button type="button" className="btn ghost sm" disabled={busy} onClick={() => void start(true)}>Relabel AI labels</button></>}>
    <div className="audience-metrics"><div><b>{status.labelled_ai}</b><span>AI-labelled</span></div><div><b>{status.labelled_curator}</b><span>Curator</span></div><div><b>{status.unlabelled}</b><span>Unlabelled</span></div><div><b>{status.queued}</b><span>Queued</span></div><div><b>{status.failed}</b><span>Failed</span></div></div>
    <p className="hint">{status.statements} statements · {formatCost(status.cost_usd)} estimated total cost · {status.provider} / {status.model} · Automatic labelling is <b>{status.automatic ? 'on' : 'off'}</b>. <Link to={{ view: 'settings', section: 'limits' }}>Change it under Limits.</Link></p>
    {status.backfill && <Notice tone={running ? 'info' : 'success'}>{running ? `Labelling ${status.backfill.labelled} of ${status.backfill.queued} queued statements… Estimated cost since start: ${formatCost(status.backfill.cost_usd)}.` : 'Backfill finished.'}</Notice>}
    {status.last_error && <Notice tone="error">Last labelling error: {status.last_error}</Notice>}
    {error && <Notice tone="error">{error}</Notice>}
  </Card>;
}

function AudienceEditor({ audience, onCancel, onSaved }: { audience: AudienceView | null; onCancel: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<AudienceDraft>(() => ({ id: audience?.id || '', name: audience?.name || '', scope: audience?.scope || 'internal', description: audience?.description || '' }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      if (audience) await putJSON<{ id: string }>(`/api/audiences/${enc(audience.id)}`, { name: draft.name.trim(), scope: draft.scope, description: draft.description.trim(), revision: audience.version });
      else await postJSON<{ id: string }>('/api/audiences', { name: draft.name.trim(), scope: draft.scope, description: draft.description.trim(), ...(draft.id.trim() ? { id: draft.id.trim() } : {}) });
      onSaved();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <form className="subcard" onSubmit={save}><fieldset disabled={busy} className="stack">
    <h3>{audience ? `Edit ${audience.name}` : 'New audience'}</h3>
    {error && <Notice tone="error">{error}</Notice>}
    <div className="field-grid">
      {!audience && <label className="field"><span>ID (optional)</span><input className="input" value={draft.id} maxLength={64} pattern="[a-z0-9]+(-[a-z0-9]+)*" placeholder="external-technical" onChange={event => setDraft(value => ({ ...value, id: event.target.value }))} /></label>}
      <label className="field"><span>Name</span><input className="input" required maxLength={100} value={draft.name} onChange={event => setDraft(value => ({ ...value, name: event.target.value }))} /></label>
      <label className="field"><span>Scope</span><select className="input" value={draft.scope} onChange={event => setDraft(value => ({ ...value, scope: event.target.value === 'external' ? 'external' : 'internal' }))}><option value="internal">Internal</option><option value="external">External</option></select></label>
    </div>
    <label className="field"><span>Description</span><textarea className="input" rows={4} required maxLength={4000} value={draft.description} onChange={event => setDraft(value => ({ ...value, description: event.target.value }))} /></label>
    <div className="row gap-sm"><button type="submit" className="btn primary sm">{busy ? 'Saving…' : 'Save audience'}</button><button type="button" className="btn ghost sm" onClick={onCancel}>Cancel</button></div>
  </fieldset></form>;
}

function AudienceList({ data, onReload, onFilter }: { data: AudiencesResponse; onReload: () => void; onFilter: (filter: StatementFilter) => void }) {
  const [editing, setEditing] = useState<AudienceView | 'new' | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mutate = async (audience: AudienceView, restore: boolean) => {
    if (!restore && !window.confirm(`Retire ${audience.name}? Its history will remain.`)) return;
    setBusyId(audience.id); setError(null);
    try {
      if (restore) await putJSON<{ id: string }>(`/api/audiences/${enc(audience.id)}`, { name: audience.name, scope: audience.scope, description: audience.description, revision: audience.version });
      else await postJSON<{ retired: true }>(`/api/audiences/${enc(audience.id)}/retire`, { revision: audience.version });
      onReload();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusyId(null); }
  };
  const saved = () => { setEditing(null); onReload(); };
  return <Card title="Audiences" actions={data.can_configure && <button type="button" className="btn sm" onClick={() => setEditing('new')}>New audience</button>}>
    <p className="muted">Unlabelled statements fail closed: they are visible to internal audiences only.</p>
    {error && <Notice tone="error">{error}</Notice>}
    {editing && <AudienceEditor key={editing === 'new' ? 'new' : editing.id} audience={editing === 'new' ? null : editing} onCancel={() => setEditing(null)} onSaved={saved} />}
    <div className="audience-list">{data.audiences.map(audience => <article key={audience.id} className={`audience-item${audience.retired ? ' retired' : ''}`}>
      <div className="audience-item-head"><h3>{audience.name}</h3><AudienceBadge scope={audience.scope} />{audience.default && <span className="status-badge ok">Default</span>}{audience.retired && <span className="status-badge">Retired</span>}</div>
      <p>{audience.description}</p>
      <div className="audience-item-meta">{audience.retired ? <><span>{audience.visible_statements} of {data.statements} visible</span><span>{audience.unlabelled_statements} unlabelled</span></> : <><button type="button" className="link-btn" onClick={() => onFilter({ audience: audience.id, visibility: 'visible', state: '' })}>{audience.visible_statements} of {data.statements} visible</button><button type="button" className="link-btn" onClick={() => onFilter({ audience: '', visibility: '', state: 'unlabelled' })}>{audience.unlabelled_statements} unlabelled</button></>}<span>{audience.profiles.length ? `Profiles: ${audience.profiles.join(', ')}` : 'No writing profiles'}</span></div>
      {data.can_configure && <div className="row gap-sm wrap">{!audience.retired && <button type="button" className="btn ghost xs" disabled={busyId === audience.id} onClick={() => setEditing(audience)}>Edit</button>}{audience.retired ? <button type="button" className="btn ghost xs" disabled={busyId === audience.id} onClick={() => void mutate(audience, true)}>Restore</button> : <button type="button" className="btn danger xs" disabled={busyId === audience.id} onClick={() => void mutate(audience, false)}>Retire</button>}</div>}
    </article>)}</div>
  </Card>;
}

function StatementFilterList({ audiences, filter, onFilter }: { audiences: AudienceView[]; filter: StatementFilter; onFilter: (filter: StatementFilter) => void }) {
  const [offset, setOffset] = useState(0);
  const load = useCallback((signal: AbortSignal) => {
    const query = new URLSearchParams({ offset: String(offset), limit: '50' });
    if (filter.audience) query.set('audience', filter.audience);
    if (filter.audience && filter.visibility) query.set('visibility', filter.visibility);
    if (filter.state) query.set('state', filter.state);
    return getJSON<AudienceStatementPage>(`/api/audiences/statements?${query}`, signal);
  }, [filter, offset]);
  const { state, reload } = useAsync(load);
  const change = (patch: Partial<StatementFilter>) => { const next = { ...filter, ...patch }; if ('audience' in patch && !patch.audience) next.visibility = ''; setOffset(0); onFilter(next); };
  const data = state.status === 'ready' ? state.data : state.previous;
  return <Card title="Statements">
    <div className="field-grid audience-filters">
      <label className="field"><span>Audience</span><select className="input" value={filter.audience} onChange={event => change({ audience: event.target.value })}><option value="">Any audience</option>{audiences.filter(audience => !audience.retired).map(audience => <option key={audience.id} value={audience.id}>{audience.name}</option>)}</select></label>
      {filter.audience && <label className="field"><span>Visibility</span><select className="input" value={filter.visibility} onChange={event => change({ visibility: event.target.value === 'visible' || event.target.value === 'hidden' ? event.target.value : '' })}><option value="">Any visibility</option><option value="visible">Visible</option><option value="hidden">Hidden</option></select></label>}
      <label className="field"><span>Label state</span><select className="input" value={filter.state} onChange={event => change({ state: isLabelState(event.target.value) ? event.target.value : '' })}><option value="">Any state</option><option value="unlabelled">Unlabelled</option><option value="ai">AI</option><option value="curator">Curator</option><option value="text_changed">Text changed since decision</option><option value="queued">Queued</option></select></label>
    </div>
    {state.status === 'loading' && !data && <Loading what="statements" />}
    {state.status === 'error' && !data && <LoadError error={state.error} what="statements" onRetry={reload} />}
    {state.status === 'error' && data && <LoadError error={state.error} what="the current statement filters" onRetry={reload} />}
    {data && <><p className="hint">{data.total} matching statement{data.total === 1 ? '' : 's'}.</p><div className="audience-statements">{data.statements.map(statement => <Fragment key={statement.id}><Link to={{ view: 'statement', id: statement.id }} className="audience-statement"><KindTag kind={statement.kind} /><span className="audience-statement-text">{statement.text}</span><span className="audience-statement-label">{labelSummary(statement.label, statement.queued)}</span></Link>{statement.label?.text_changed_at && data.can_curate && <TextChangedActions statementId={statement.id} onDone={reload} />}</Fragment>)}{data.statements.length === 0 && <p className="muted">No statements match these filters.</p>}</div>
      <div className="row gap-sm audience-pages"><button type="button" className="btn ghost sm" disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - 50))}>Previous</button><span className="hint">{data.total ? `${offset + 1}–${Math.min(offset + 50, data.total)} of ${data.total}` : '0 results'}</span><button type="button" className="btn ghost sm" disabled={offset + 50 >= data.total} onClick={() => setOffset(value => value + 50)}>Next</button></div></>}
  </Card>;
}

export function AudiencesSettings() {
  const { state, reload } = useAsync(useCallback((signal: AbortSignal) => getJSON<AudiencesResponse>('/api/audiences', signal), []));
  const [filter, setFilter] = useState<StatementFilter>({ audience: '', visibility: '', state: '' });
  const data = dataOf(state);
  if (!data && state.status === 'loading') return <Loading what="audiences" />;
  if (!data && state.status === 'error') return <LoadError error={state.error} what="audiences" onRetry={reload} />;
  if (!data) return null;
  const prefilter = (next: StatementFilter) => { setFilter(next); requestAnimationFrame(() => document.querySelector('.audience-filters')?.scrollIntoView({ behavior: 'smooth', block: 'start' })); };
  return <>{state.status === 'error' && <LoadError error={state.error} what="audiences" onRetry={reload} />}<LabellingCard data={data} onReload={reload} /><AudienceList data={data} onReload={reload} onFilter={prefilter} /><StatementFilterList key={`${filter.audience}:${filter.visibility}:${filter.state}`} audiences={data.audiences} filter={filter} onFilter={setFilter} /></>;
}
