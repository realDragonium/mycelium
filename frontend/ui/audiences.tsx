import { Fragment, useCallback, useEffect, useState, type FormEvent } from 'react';
import { deleteJSON, enc, errorMessage, getJSON, postJSON, putJSON } from './api';
import { Card, KindTag, LoadError, Loading, Notice, formatDate } from './lib';
import { Link } from './router';
import { dataOf, useAsync } from './use-async';

export type AudienceScope = 'internal' | 'external';
export interface AudienceRef { id: string; name: string; scope: AudienceScope }
export interface AudienceLabel {
  audiences: string[]; source: 'ai' | 'curator'; reason: string; model: string | null;
  labelled_at: string; labelled_by: string | null; text_changed_at: string | null; pending: string[];
  narrowed: Narrowed | null; spot_check: KeptOnEdit | null;
}
interface KeptOnEdit { audiences: string[]; old_text: string; at: string }
export interface Narrowed { previous: string[]; lost: string[]; reason: string }
export interface AudienceView extends AudienceRef {
  description: string; includes: string[]; version: number; retired: boolean; default: boolean; profiles: string[];
  visible_statements: number; unlabelled_statements: number; pending_statements: number;
}
export interface AudienceStatus {
  statements: number; labelled_ai: number; labelled_curator: number; unlabelled: number; queued: number; failed: number;
  last_error: string | null; cost_usd: number; automatic: boolean; confirm_external_grants: boolean; model: string; provider: string;
  backfill: BackfillProgress | null;
}
interface Backfill { started_at: string; queued: number }
interface BackfillProgress extends Backfill { labelled: number; cost_usd: number }
export interface AudiencesResponse {
  audiences: AudienceView[]; can_configure: boolean; statements: number; unlabelled: number; pending: number; labelling: AudienceStatus;
}

interface AudienceStatement {
  id: string; kind: string; text: string; label: AudienceLabel | null; queued: boolean;
}
interface AudienceStatementPage { statements: AudienceStatement[]; total: number; can_curate: boolean }
type Visibility = '' | 'visible' | 'hidden';
type LabelState = '' | 'unlabelled' | 'ai' | 'curator' | 'text_changed' | 'pending' | 'queued';
const LABEL_STATES = ['unlabelled', 'ai', 'curator', 'text_changed', 'pending', 'queued'] as const;
const isLabelState = (value: string): value is Exclude<LabelState, ''> => (LABEL_STATES as readonly string[]).includes(value);
interface StatementFilter { audience: string; visibility: Visibility; state: LabelState }
interface AudienceDraft { id: string; name: string; scope: AudienceScope; description: string; includes: string[] }

export const AudienceBadge = ({ scope }: { scope: AudienceScope }) => <span className={`audience-badge ${scope}`}>{scope}</span>;
export const AudienceIdentity = ({ audience }: { audience: AudienceRef }) => <span className="audience-identity"><span>{audience.name}</span><AudienceBadge scope={audience.scope} /></span>;

const formatCost = (value: number | null) => value === null ? '—' : `$${value.toFixed(value >= 1 ? 2 : 4)}`;
const labelSummary = (label: AudienceLabel | null, queued: boolean) => queued ? 'Queued for labelling' : !label ? 'Unlabelled' : `${label.source === 'ai' ? `AI${label.model ? ` · ${label.model}` : ''}` : `Curator${label.labelled_by ? ` · ${label.labelled_by}` : ''}${label.text_changed_at ? ' · text changed since decision' : ''}`}${label.pending.length ? ' · waiting for confirmation' : ''}${label.narrowed ? ` · narrowed after an edit: ${label.narrowed.reason}` : ''}${label.spot_check ? ' · edited, external grant kept for a spot check' : ''}`;

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

interface PendingConcept { id: string; name: string }
interface PendingStatement { id: string; kind: string; text: string; reason: string; model: string | null; labelled_at: string; concepts: PendingConcept[] }
interface PendingGroup { concept: PendingConcept | null; statements: PendingStatement[] }
interface PendingGrants { audience_id: string; total: number; groups: PendingGroup[]; can_curate: boolean; sample_size: number; min_sample_precision_percent: number }
interface Accepted { accepted: number; sample_size: number; precision: number; below_threshold: boolean }
type Verdict = 'confirm' | 'reject';

const decidePending = (audienceId: string, statementIds: string[], decision: Verdict) =>
  postJSON<{ decided: number }>(`/api/audiences/${enc(audienceId)}/pending/decide`, { statement_ids: statementIds, decision });
const percent = (value: number) => `${Math.round(value * 1000) / 10}%`;
const groupName = (group: PendingGroup) => group.concept?.name || 'No concept';

export function PendingGrantActions({ audienceId, statementIds, onDone, all = false }: { audienceId: string; statementIds: string[]; onDone: (verdict: Verdict) => void; all?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const act = async (verdict: Verdict) => {
    if (all && !window.confirm(`${verdict === 'confirm' ? 'Confirm' : 'Reject'} all ${statementIds.length} grants in this group?`)) return;
    setBusy(true); setError(null);
    try { await decidePending(audienceId, statementIds, verdict); onDone(verdict); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <span className="row gap-sm wrap">
    <button type="button" className="btn sm" disabled={busy} onClick={() => void act('confirm')}>{all ? 'Confirm all' : 'Confirm'}</button>
    <button type="button" className="btn ghost sm" disabled={busy} onClick={() => void act('reject')}>{all ? 'Reject all' : 'Reject'}</button>
    {error && <Notice tone="error">{error}</Notice>}
  </span>;
}

function PendingRow({ audienceId, statement, canCurate, verdict, onDone }: { audienceId: string; statement: PendingStatement; canCurate: boolean; verdict?: Verdict; onDone: (verdict: Verdict) => void }) {
  return <div className="pending-grant">
    <Link to={{ view: 'statement', id: statement.id }} className="pending-grant-text"><KindTag kind={statement.kind} /><span>{statement.text}</span></Link>
    <p className="pending-grant-reason">{statement.reason}</p>
    {statement.concepts.length > 0 && <div className="pending-grant-concepts">{statement.concepts.map(concept => <Link key={concept.id} to={{ view: 'entity', id: concept.id }} className="audience-badge">{concept.name}</Link>)}</div>}
    <div className="pending-grant-actions">{verdict ? <span className={`status-badge ${verdict === 'confirm' ? 'ok' : 'bad'}`}>{verdict === 'confirm' ? 'Confirmed' : 'Rejected'}</span> : canCurate && <PendingGrantActions audienceId={audienceId} statementIds={[statement.id]} onDone={onDone} />}</div>
  </div>;
}

function SampleReview({ audience, data, sample, verdicts, onVerdict, onAccepted, onClose }: {
  audience: AudienceView; data: PendingGrants; sample: PendingGroup[]; verdicts: Record<string, Verdict>;
  onVerdict: (id: string, verdict: Verdict) => void; onAccepted: (result: Accepted) => void; onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ids = sample.flatMap(group => group.statements.map(statement => statement.id));
  const confirmed = ids.filter(id => verdicts[id] === 'confirm').length;
  const rejected = ids.filter(id => verdicts[id] === 'reject').length;
  const decided = confirmed + rejected;
  const precision = decided ? confirmed / decided : null;
  const low = precision !== null && precision * 100 < data.min_sample_precision_percent;
  const acceptRest = async () => {
    const warning = low ? ` The sample's precision ${percent(precision)} is below ${data.min_sample_precision_percent}%.` : '';
    if (!window.confirm(`Confirm all ${data.total} remaining grants to ${audience.name}?${warning}`)) return;
    setBusy(true); setError(null);
    try { onAccepted(await postJSON<Accepted>(`/api/audiences/${enc(audience.id)}/pending/accept-rest`, { sample: ids })); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <div className="pending-sample">
    <div className="audience-metrics"><div><b>{ids.length}</b><span>In the sample</span></div><div><b>{decided}</b><span>Decided</span></div><div><b>{confirmed}</b><span>Confirmed</span></div><div><b>{rejected}</b><span>Rejected</span></div><div><b>{precision === null ? '—' : percent(precision)}</b><span>Precision (warn below {data.min_sample_precision_percent}%)</span></div></div>
    {low && <Notice tone="warn"><span>The AI was right on {percent(precision)} of this sample, below {data.min_sample_precision_percent}%. Rather than accepting the rest, sharpen the audience descriptions or the audience labelling instructions under <Link to={{ view: 'settings', section: 'prompts' }}>Prompts</Link>, then click <b>Relabel AI labels</b>.</span></Notice>}
    {error && <Notice tone="error">{error}</Notice>}
    {data.can_curate && <div className="row gap-sm wrap"><button type="button" className={`btn sm${low ? ' ghost' : ' primary'}`} disabled={busy || !decided || !data.total} onClick={() => void acceptRest()}>Accept the rest ({data.total})</button><button type="button" className="btn ghost sm" disabled={busy} onClick={onClose}>Back to the list</button>{!decided && <span className="hint">Decide at least one sampled grant first.</span>}</div>}
    {sample.map(group => <section key={group.concept?.id || 'none'} className="pending-group"><h4>{groupName(group)} <span className="count-pill">{group.statements.length}</span></h4>
      {group.statements.map(statement => <PendingRow key={statement.id} audienceId={audience.id} statement={statement} canCurate={data.can_curate} verdict={verdicts[statement.id]} onDone={verdict => onVerdict(statement.id, verdict)} />)}
    </section>)}
  </div>;
}

function PendingAudience({ audience, onChanged }: { audience: AudienceView; onChanged: () => void }) {
  const { state, reload } = useAsync(useCallback((signal: AbortSignal) => getJSON<PendingGrants>(`/api/audiences/${enc(audience.id)}/pending`, signal), [audience.id]));
  const [sample, setSample] = useState<PendingGroup[] | null>(null);
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({});
  const [accepted, setAccepted] = useState<Accepted | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const data = dataOf(state);
  const changed = () => { reload(); onChanged(); };
  const draw = async () => {
    setDrawing(true); setError(null); setAccepted(null);
    try { setSample((await getJSON<{ groups: PendingGroup[] }>(`/api/audiences/${enc(audience.id)}/pending/sample`)).groups); setVerdicts({}); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setDrawing(false); }
  };
  return <article className="pending-audience">
    <div className="audience-item-head"><h3>{audience.name}</h3><AudienceBadge scope={audience.scope} /><span className="status-badge open">{data?.total ?? audience.pending_statements} waiting</span>
      {data?.can_curate && !sample && !!data.total && <button type="button" className="btn sm" disabled={drawing} onClick={() => void draw()}>{drawing ? 'Drawing…' : `Review a sample of ${Math.min(data.sample_size, data.total)}`}</button>}</div>
    {accepted && <Notice tone={accepted.below_threshold ? 'warn' : 'success'}>Accepted {accepted.accepted} grants after a sample of {accepted.sample_size} with {percent(accepted.precision)} precision.</Notice>}
    {error && <Notice tone="error">{error}</Notice>}
    {!data && state.status === 'loading' && <Loading what="waiting grants" />}
    {!data && state.status === 'error' && <LoadError error={state.error} what="waiting grants" onRetry={reload} />}
    {data && sample && <SampleReview audience={audience} data={data} sample={sample} verdicts={verdicts}
      onVerdict={(id, verdict) => { setVerdicts(current => ({ ...current, [id]: verdict })); changed(); }}
      onAccepted={result => { setAccepted(result); setSample(null); changed(); }} onClose={() => setSample(null)} />}
    {data && !sample && !data.total && <p className="hint">No grants are waiting.</p>}
    {data && !sample && data.groups.map(group => <details key={group.concept?.id || 'none'} className="pending-group">
      <summary><span className="pending-group-name">{groupName(group)} <span className="count-pill">{group.statements.length}</span></span>{data.can_curate && <span onClick={event => event.preventDefault()}><PendingGrantActions all audienceId={audience.id} statementIds={group.statements.map(statement => statement.id)} onDone={changed} /></span>}</summary>
      {group.statements.map(statement => <PendingRow key={statement.id} audienceId={audience.id} statement={statement} canCurate={data.can_curate} onDone={changed} />)}
    </details>)}
  </article>;
}

interface SpotCheck extends KeptOnEdit { id: string; kind: string; text: string }
interface SpotChecks { statements: SpotCheck[]; can_curate: boolean }

function SpotCheckRow({ statement, names, canCurate, onDone }: { statement: SpotCheck; names: (id: string) => string; canCurate: boolean; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const act = async (decision: 'confirm' | 'narrow') => {
    setBusy(true); setError(null);
    try { await postJSON<{ decided: number }>(`/api/statements/${enc(statement.id)}/audiences/spot-check`, { decision }); onDone(); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <div className="pending-grant">
    <Link to={{ view: 'statement', id: statement.id }} className="pending-grant-text"><KindTag kind={statement.kind} /><span>{statement.text}</span></Link>
    <p className="pending-grant-reason">Was: {statement.old_text}</p>
    <p className="hint">Still visible to {statement.audiences.map(names).join(', ')} · edited {formatDate(statement.at)}</p>
    {canCurate && <div className="pending-grant-actions"><span className="row gap-sm wrap">
      <button type="button" className="btn sm" disabled={busy} onClick={() => void act('confirm')}>Confirm</button>
      <button type="button" className="btn ghost sm" disabled={busy} onClick={() => void act('narrow')}>Narrow</button>
      {error && <Notice tone="error">{error}</Notice>}
    </span></div>}
  </div>;
}

function SpotCheckCard({ data, onReload }: { data: AudiencesResponse; onReload: () => void }) {
  const { state, reload } = useAsync(useCallback((signal: AbortSignal) => getJSON<SpotChecks>('/api/audiences/spot-checks', signal), []));
  const checks = dataOf(state);
  const names = (id: string) => data.audiences.find(audience => audience.id === id)?.name || id;
  return <Card title={<>Recently edited external statements {!!checks?.statements.length && <span className="status-badge open">{checks.statements.length}</span>}</>}>
    <p className="muted">An edit kept these statements' confirmed external grants in force. Check the new text: <b>Confirm</b> keeps the grant, <b>Narrow</b> withdraws it; internal audiences keep seeing the statement.</p>
    {!checks && state.status === 'loading' && <Loading what="recently edited statements" />}
    {!checks && state.status === 'error' && <LoadError error={state.error} what="recently edited statements" onRetry={reload} />}
    {checks && !checks.statements.length && <p className="hint">Nothing to check.</p>}
    {checks?.statements.map(statement => <SpotCheckRow key={statement.id} statement={statement} names={names} canCurate={checks.can_curate} onDone={() => { reload(); onReload(); }} />)}
  </Card>;
}

function PendingGrantsCard({ data, onReload }: { data: AudiencesResponse; onReload: () => void }) {
  const waiting = data.audiences.filter(audience => !audience.retired && (audience.scope === 'external' || audience.pending_statements > 0));
  return <Card title={<>Waiting for confirmation {data.pending > 0 && <span className="status-badge open">{data.pending}</span>}</>}>
    <p className="muted">{data.labelling.confirm_external_grants
      ? 'An AI grant that would newly show a statement to an external audience waits here; until a curator confirms it, that audience does not see the statement.'
      : 'Confirm external grants is off: the AI\'s external grants apply at once.'} <Link to={{ view: 'settings', section: 'limits' }}>Change it under Limits.</Link></p>
    {waiting.length === 0 && <p className="hint">No external audiences.</p>}
    {waiting.map(audience => <PendingAudience key={audience.id} audience={audience} onChanged={onReload} />)}
  </Card>;
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

// An external audience may only include external audiences.
const includable = (others: AudienceView[], scope: AudienceScope) => others.filter(other => !other.retired && (scope === 'internal' || other.scope === 'external'));

function AudienceEditor({ audience, others, onCancel, onSaved }: { audience: AudienceView | null; others: AudienceView[]; onCancel: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<AudienceDraft>(() => ({ id: audience?.id || '', name: audience?.name || '', scope: audience?.scope || 'internal', description: audience?.description || '', includes: audience?.includes || [] }));
  const options = includable(others, draft.scope);
  const includes = draft.includes.filter(id => options.some(option => option.id === id));
  const toggle = (id: string) => setDraft(value => ({ ...value, includes: value.includes.includes(id) ? value.includes.filter(item => item !== id) : [...value.includes, id] }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      if (audience) await putJSON<{ id: string }>(`/api/audiences/${enc(audience.id)}`, { name: draft.name.trim(), scope: draft.scope, description: draft.description.trim(), includes, revision: audience.version });
      else await postJSON<{ id: string }>('/api/audiences', { name: draft.name.trim(), scope: draft.scope, description: draft.description.trim(), includes, ...(draft.id.trim() ? { id: draft.id.trim() } : {}) });
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
    {!!options.length && <div className="field"><span>Includes</span><p className="hint">This audience also sees everything the audiences it includes may see.</p><div className="audience-checks">{options.map(option => <label key={option.id} className="check"><input type="checkbox" checked={includes.includes(option.id)} onChange={() => toggle(option.id)} /><AudienceIdentity audience={option} /></label>)}</div></div>}
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
      if (restore) await putJSON<{ id: string }>(`/api/audiences/${enc(audience.id)}`, { name: audience.name, scope: audience.scope, description: audience.description, includes: audience.includes.filter(id => includable(data.audiences, audience.scope).some(other => other.id === id)), revision: audience.version });
      else await postJSON<{ retired: true }>(`/api/audiences/${enc(audience.id)}/retire`, { revision: audience.version });
      onReload();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusyId(null); }
  };
  const saved = () => { setEditing(null); onReload(); };
  return <Card title="Audiences" actions={data.can_configure && <button type="button" className="btn sm" onClick={() => setEditing('new')}>New audience</button>}>
    <p className="muted">Unlabelled statements fail closed: they are visible to internal audiences only.</p>
    {error && <Notice tone="error">{error}</Notice>}
    {editing && <AudienceEditor key={editing === 'new' ? 'new' : editing.id} audience={editing === 'new' ? null : editing} others={data.audiences.filter(other => editing === 'new' || other.id !== editing.id)} onCancel={() => setEditing(null)} onSaved={saved} />}
    <div className="audience-list">{data.audiences.map(audience => <article key={audience.id} className={`audience-item${audience.retired ? ' retired' : ''}`}>
      <div className="audience-item-head"><h3>{audience.name}</h3><AudienceBadge scope={audience.scope} />{audience.default && <span className="status-badge ok">Default</span>}{audience.retired && <span className="status-badge">Retired</span>}</div>
      <p>{audience.description}</p>
      {!!audience.includes.length && <p className="hint">Includes {audience.includes.map(id => data.audiences.find(other => other.id === id)?.name || id).join(', ')}.</p>}
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
      <label className="field"><span>Label state</span><select className="input" value={filter.state} onChange={event => change({ state: isLabelState(event.target.value) ? event.target.value : '' })}><option value="">Any state</option><option value="unlabelled">Unlabelled</option><option value="ai">AI</option><option value="curator">Curator</option><option value="text_changed">Text changed since decision</option><option value="pending">Waiting for confirmation</option><option value="queued">Queued</option></select></label>
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
  return <>{state.status === 'error' && <LoadError error={state.error} what="audiences" onRetry={reload} />}<LabellingCard data={data} onReload={reload} /><PendingGrantsCard data={data} onReload={reload} /><SpotCheckCard data={data} onReload={reload} /><AudienceList data={data} onReload={reload} onFilter={prefilter} /><StatementFilterList key={`${filter.audience}:${filter.visibility}:${filter.state}`} audiences={data.audiences} filter={filter} onFilter={setFilter} /></>;
}
