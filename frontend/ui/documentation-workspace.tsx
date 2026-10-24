import React from 'react';
import { errorMessage, getJSON, HttpError, postJSON } from './api';
import { substrate } from './data';
import { PageHeader } from './lib';
import { Link } from './router';
import { AudienceIdentity, type AudienceRef } from './audiences';

interface DocumentationRoute { tab: string; document: string | null; revision: string | null; run: string | null; profile: string | null }
interface DocumentationModelOption {
  provider: string; label: string; model: string | null; reasoning_effort: string | null; available: boolean; reason: string | null;
}
interface DocumentationOptions {
  default_provider: string;
  models: DocumentationModelOption[];
  can_generate: boolean;
  guideline_sets: Record<string, string[]>;
  profile_audiences: Record<string, AudienceRef | null>;
  max_prompt_chars: number;
}
interface AgentTask {
  id: string; kind: string; status: 'waiting' | 'claimed' | 'in_review' | 'done' | 'failed';
  claimed_by: string | null; expires_at: string | null; failures: number;
  findings: { check: string; where: string | null; problem: string }[];
  release_reason: string | null; updated_at: string; error: string | null;
}
interface DocumentationRun {
  id: string; prompt: string; provider: string; model: string | null; reasoning_effort: string | null;
  status: string; queue_position: number | null; created_at: string; document_id: string | null; result_revision: number | null;
  target_document_id: string | null; target_revision: number | null;
  revision_base: string | null; error: string | null; draft_title?: string | null; draft_body?: string | null;
  summary: RunSummary | null; review_notes: ReviewNote[]; retryable?: boolean; agent_task?: AgentTask | null;
  retry_of: string | null; attempt: number; recovery: 'none' | 'retried' | 'gave_up' | null; recovery_note: string | null;
  delivery: 'none' | 'publishing' | 'published' | 'failed' | null; delivery_error: string | null;
}
interface RunSummary {
  activity: string | null; turns: number; duration_s: number;
  tokens: { input: number; cache_read: number; cache_creation: number; output: number };
  statements_retrieved: number; statements_cited: number; gaps_filed: number;
  cited_statement_ids?: string[];
  review_findings?: ReviewNote[];
}
interface ReviewNote { check: 'exposure' | 'conformance'; where: string; problem: string }
interface DeliveryCoordinates { host: string; owner: string; repo: string; base_branch: string }
interface PullRequest { number: number; state: string; refreshed_at: string | null }
interface StatementChange {
  statement_id: string; change: 'edited' | 'deleted' | 'merged' | 'no_longer_visible'; old_text: string; new_text: string | null; merged_into: string | null;
}
interface Staleness { status: 'unknown' | 'current' | 'out_of_date'; changes: StatementChange[] }
interface DocumentationSummary {
  id: string; slug: string; title: string; guideline_set: string; document_type: string;
  audience: AudienceRef | null;
  current_revision: number; published_revision: number | null; delivery_status: string;
  updated_at: string; anchor_entity_id: string | null;
  delivery_destination: string | null; delivery_path: string | null; delivery_reference: string | null;
  delivery_coordinates: DeliveryCoordinates | null; pull_request: PullRequest | null; last_run_id?: string | null;
  stale: Staleness;
}
interface DocumentationDocument extends DocumentationSummary {
  body: string; body_html: string; statement_ids: string[]; review: unknown; last_run_id: string | null;
}
interface DocumentationRevisionSummary {
  revision: number; slug: string; title: string; guideline_set: string; document_type: string;
  created_at: string; run_id: string | null;
}
interface DocumentationRevision extends DocumentationRevisionSummary {
  statement_ids: string[]; review: unknown; body: string; body_html: string;
}
interface DocumentationDestination { name: string; path_template: string; coordinates: DeliveryCoordinates }
interface LoadedDocument { current: DocumentationDocument; history: DocumentationRevisionSummary[]; selected: DocumentationDocument | DocumentationRevision }
interface PendingEdit { title: string; body: string; expectedRevision: number | undefined }
interface PlanItem {
  id: string; action: 'create' | 'update'; title: string; document_type: string; anchor_entity_id: string | null; anchor_name: string | null;
  document_id: string | null; rationale: string; priority: 'high' | 'medium' | 'low'; statement_ids: string[];
  state: 'proposed' | 'approved' | 'dismissed'; run: { id: string; status: string; queue_position: number | null; document_id: string | null; review_notes: boolean } | null;
  maintenance: boolean; start_error: string | null; given_up: string | null;
  review: { decision: 'approve' | 'dismiss' | null; reason: string; reviewer: string | null; at: string; failures: number } | null;
}
interface PlanSummary {
  id: string; created_at: string; finished_at: string | null; outcome: 'planned' | 'failed' | null; error: string | null; activity: string | null;
  provider: string | null; model: string | null; tokens: number | null; proposed: number | null; dropped: Record<string, number>; agent_task?: AgentTask | null;
}
interface DocumentationPlan {
  guideline_set: string; audience: AudienceRef | null; unavailable: string | null; latest: PlanSummary | null; items: PlanItem[];
  stale: { document_id: string; title: string; document_type: string; revision: number; changes: StatementChange[] }[];
  coverage: { entity_id: string; name: string; statements: number }[];
  uncovered_statements: number; uncovered: { id: string; kind: string; text: string }[]; dismissed_statements: number;
  dismissed_uncovered: { id: string; kind: string; text: string }[];
  planning: 'off' | 'propose' | 'write'; plan_review: 'person' | 'ai'; review_task: AgentTask | null;
  recovery: 'person' | 'ai'; recovery_note: string | null;
  visible_statements: number; new_since_plan: number | null; replan_hint: boolean; dismissed: number; approve_batch: number;
}
interface ApprovedItem { item_id: string; run: DocumentationRun | null; error: string | null }
interface MaintenanceEntry {
  document_id: string; title: string; guideline_set: string; revision: number; action: 'propose' | 'auto-revise';
  state: 'proposed' | 'approved' | 'dismissed' | 'running' | 'revised' | 'refused' | 'failed';
  at: string; changes: StatementChange[]; run_id: string | null; new_revision: number | null; error: string | null;
  delivery: 'none' | 'publishing' | 'published' | 'failed' | null; pull_request: { number: number; url: string | null; state: string | null } | null; waiting: boolean;
}
interface RevisionDiff { from_revision: number; to_revision: number; lines: { op: '+' | '-' | ' ' | '@'; text: string }[] }

const docGet = <T,>(path: string, signal?: AbortSignal) => getJSON<T>('/api/documentation/' + path, signal);
const docPost = <T,>(path: string, body: unknown) => postJSON<T>('/api/documentation/' + path, body);
const isBothSidesEdited = (error: unknown) => error instanceof HttpError
  && !!error.body && typeof error.body === 'object' && 'code' in error.body && error.body.code === 'both_sides_edited';
const RUN_STATUSES: Record<string, string> = { queued: 'Queued', waiting_for_agent: 'Waiting for an agent', running: 'Generating and reviewing', document_written: 'Saved', document_superseded: 'Saved · newer revision exists', nothing_written: 'No document saved', failed: 'Failed' };
const DELIVERY_STATUSES: Record<string, string> = { unpublished: 'Internal only', published: 'Published to GitHub', changes_pending: 'Changes awaiting publication', merged: 'Pull request merged', closed: 'Pull request closed without merging' };
const PULL_REQUEST_STATES: Record<string, string> = { open: 'Open for review', merged: 'Merged', closed: 'Closed without merging' };

function docRoute(): DocumentationRoute {
  const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
  return { tab: params.get('tab') || (params.has('run') ? 'runs' : 'library'), document: params.get('document'), revision: params.get('revision'), run: params.get('run'), profile: params.get('profile') };
}

function docNavigate(next: Record<string, string | number | null | undefined>) {
  const params = new URLSearchParams();
  Object.entries(next).forEach(([key, value]) => { if (value) params.set(key, String(value)); });
  const query = params.toString();
  window.location.hash = '/documentation' + (query ? '?' + query : '');
}

const docActive = (run: DocumentationRun) => ['queued', 'waiting_for_agent', 'running'].includes(run.status);
const docStatus = ({ status, queue_position }: { status: string; queue_position: number | null }) =>
  status === 'queued' && queue_position ? `Queued · ${queue_position === 1 ? 'next to start' : `${queue_position} in line`}` : RUN_STATUSES[status] || status;
const docDeliveryStatus = (status: string) => DELIVERY_STATUSES[status] || status;
const docPullRequestState = (state: string) => PULL_REQUEST_STATES[state] || 'State unknown';

// An anchor is the entity a document is about; typed by name or alias, sent by id.
const docEntityByName = (text: string) => {
  const wanted = text.trim().toLowerCase();
  return substrate.data.entities.find(entity => entity.name.toLowerCase() === wanted || (substrate.index.namesByEntity[entity.id] || []).some(name => name.text.toLowerCase() === wanted));
};
const docEntityName = (id: string) => substrate.data.entities.find(entity => entity.id === id)?.name || id;
const docDate = (value: string | null | undefined) => value ? new Date(value).toLocaleString() : 'Not recorded';
const docTokens = (count: number) => count >= 1000 ? `${(count / 1000).toFixed(count >= 100_000 ? 0 : 1)}k` : String(count);
const docDuration = (seconds: number) => seconds >= 60 ? `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s` : `${Math.round(seconds)} s`;
const docTotalTokens = ({ tokens }: RunSummary) => tokens.input + tokens.cache_read + tokens.cache_creation + tokens.output;
const docRunLine = (summary: RunSummary) => `${summary.turns} turns · ${docDuration(summary.duration_s)} · ${docTokens(docTotalTokens(summary))} tokens · ${summary.statements_cited} of ${summary.statements_retrieved} retrieved statements cited`;

function agentRunStatus(task: AgentTask) {
  if (task.status === 'waiting') return <>Waiting for an agent to claim it.{task.release_reason && <> Last released: {task.release_reason}.</>}</>;
  if (task.status === 'claimed') return <>Claimed by {task.claimed_by || 'an agent'} until {docDate(task.expires_at)}.</>;
  if (task.status === 'in_review') return <>Written; waiting for another agent's review.</>;
  if (task.status === 'failed') return <>The agent task failed{task.error ? `: ${task.error}` : '.'}</>;
  return <>The agent finished this task.</>;
}

function agentPlanStatus(task: AgentTask) {
  if (task.status === 'waiting') return <>Waiting for an agent to claim it…{task.release_reason && <> Last released: {task.release_reason}.</>}</>;
  if (task.status === 'claimed') return <>Claimed by {task.claimed_by || 'an agent'} until {docDate(task.expires_at)}…</>;
  return <>Finishing the external agent's plan…</>;
}

function DocumentationSources({ ids }: { ids: string[] }) {
  return <ol className="docw-sources">{ids.map(id => {
    const statement = substrate.index.statements[id];
    return <li key={id}>{statement
      ? <Link to={{ view: 'statement', id }} className="prov-item" title={id}><span className="pv-body"><span className="pv-title">{statement.text}</span><span className="pv-role">{statement.kind}</span></span></Link>
      : <span className="pv-role" title={id}>A statement no longer in the knowledge base</span>}</li>;
  })}</ol>;
}

function DocumentationRunSummary({ summary }: { summary: RunSummary }) {
  const { tokens } = summary;
  return <dl className="docw-summary">
    <div><dt>Turns</dt><dd>{summary.turns}</dd></div>
    <div><dt>Duration</dt><dd>{docDuration(summary.duration_s)}</dd></div>
    <div><dt>Input tokens</dt><dd>{docTokens(tokens.input + tokens.cache_read + tokens.cache_creation)} ({docTokens(tokens.cache_read)} from cache)</dd></div>
    <div><dt>Output tokens</dt><dd>{docTokens(tokens.output)}</dd></div>
    <div><dt>Statements</dt><dd>{summary.statements_cited} cited of {summary.statements_retrieved} retrieved</dd></div>
    <div><dt>Knowledge gaps filed</dt><dd>{summary.gaps_filed}</dd></div>
  </dl>;
}

function DocumentationModel({ options, value, onChange, disabled, filter }: {
  options: DocumentationOptions; value: string; onChange: (provider: string) => void; disabled?: boolean;
  filter?: (model: DocumentationModelOption) => boolean;
}) {
  return <label>Model for this run<select value={value} onChange={event => onChange(event.target.value)} disabled={disabled}>
    {options.models.filter(model => !filter || filter(model)).map(model => <option key={model.provider} value={model.provider} disabled={!model.available}>{model.provider === 'agent' ? model.label : model.model ? `${model.label} · ${model.model} · ${model.reasoning_effort ?? 'Model default'} effort${model.available ? '' : ' (unavailable)'}` : `${model.label} · no model chosen`}</option>)}
  </select></label>;
}

function DocumentationGenerator({ options, document, documents = [], onStarted }: {
  options: DocumentationOptions; document?: DocumentationDocument; documents?: DocumentationSummary[]; onStarted: (run: DocumentationRun) => void;
}) {
  const [prompt, setPrompt] = React.useState('');
  const [provider, setProvider] = React.useState(options.default_provider);
  const providerChosen = React.useRef(false);
  React.useEffect(() => { if (!providerChosen.current) setProvider(options.default_provider); }, [options.default_provider]);
  const [profile, setProfile] = React.useState('');
  const [type, setType] = React.useState('');
  const [anchor, setAnchor] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [bothEdited, setBothEdited] = React.useState(false);
  const submitting = React.useRef(false);
  const selected = options.models.find(model => model.provider === provider);
  const profileName = document?.guideline_set || profile;
  const profileAudience = profileName ? options.profile_audiences[profileName] : undefined;
  const audienceUnavailable = !!profileName && profileAudience === null;
  const allowed = options.can_generate && !!selected?.available && !audienceUnavailable;
  const anchorEntity = anchor.trim() ? docEntityByName(anchor) : null;
  const anchored = anchorEntity ? documents.find(item => item.guideline_set === profile && item.document_type === type && item.anchor_entity_id === anchorEntity.id) : undefined;
  const submit = async (event: { preventDefault: () => void }, startFromDestination = false) => {
    event.preventDefault();
    if (submitting.current || !allowed || !prompt.trim()) return;
    if (anchor.trim() && !anchorEntity) { setError('Choose a concept from the list, or clear the field.'); return; }
    submitting.current = true; setBusy(true); setError(null); setBothEdited(false);
    try {
      const run = await docPost<DocumentationRun>(document ? `documents/${encodeURIComponent(document.id)}/revisions` : 'runs', document
        ? { prompt: prompt.trim(), provider, expected_revision: document.current_revision, start_from_destination: startFromDestination }
        : { prompt: prompt.trim(), provider, guideline_set: profile || null, document_type: type || null, anchor_entity_id: anchorEntity?.id || null });
      onStarted(run);
    } catch (error) { setError(errorMessage(error)); setBothEdited(isBothSidesEdited(error)); }
    finally { submitting.current = false; setBusy(false); }
  };
  return <form onSubmit={submit} className="docw-panel">
    <h2>{document ? `Create revision of “${document.title}”` : 'Generate a document'}</h2>
    <p>{document ? `This uses internal revision ${document.current_revision}. The previous version stays in history.` : 'Describe the concept, audience, and scope. The result is saved internally for review before you publish it.'}</p>
    <fieldset disabled={busy || !options.can_generate}>
      <DocumentationModel options={options} value={provider} onChange={value => { providerChosen.current = true; setProvider(value); }} />
      {!document && <div className="docw-fields">
        <label>Writing profile<select value={profile} onChange={event => { setProfile(event.target.value); setType(''); }}><option value="">Choose automatically</option>{Object.keys(options.guideline_sets).map(name => <option key={name}>{name}</option>)}</select></label>
        <label>Document template<select value={type} disabled={!profile} onChange={event => { setType(event.target.value); if (!event.target.value) setAnchor(''); }}><option value="">Choose automatically</option>{(options.guideline_sets[profile] || []).map(name => <option key={name}>{name}</option>)}</select></label>
        <label className="docw-wide">About concept (optional)<input type="text" list="docw-anchor-entities" value={anchor} disabled={!type} onChange={event => setAnchor(event.target.value)} placeholder={type ? 'Concept name or alias' : 'Choose a profile and template first'} spellCheck={false} /></label>
        <datalist id="docw-anchor-entities">{substrate.data.entities.map(entity => <option key={entity.id} value={entity.name} />)}</datalist>
      </div>}
      {profileAudience && <p className="docw-meta">Audience: <AudienceIdentity audience={profileAudience} /></p>}
      {audienceUnavailable && <p role="alert">This profile's audience was retired. {document ? 'Change its audience in Settings before revising.' : 'Choose another profile or change its audience in Settings.'}</p>}
      {!document && <p className="docw-meta" role="status">{anchored
        ? <>This revises <a href={'#/documentation?document=' + encodeURIComponent(anchored.id)}>“{anchored.title}”</a> (revision {anchored.current_revision}), the {type} about “{anchorEntity?.name}”. Its earlier revisions stay in history.</>
        : anchorEntity ? `This creates a new ${type} about “${anchorEntity.name}”. Requesting it again later revises that document.`
        : type ? 'This creates a new document. Naming a concept gives it a stable identity: a later request for the same concept, profile and template revises it.'
        : 'This creates a new document.'}</p>}
      <label>{document ? 'What should change?' : 'What should be documented?'}<textarea required maxLength={options.max_prompt_chars} value={prompt} onChange={event => setPrompt(event.target.value)} placeholder={document ? 'Explain what to improve, add, or remove.' : 'For example: Explain invitation reminders for administrators, including setup and examples.'} /></label>
      <button type="submit" disabled={!allowed || !prompt.trim()}>{busy ? 'Starting…' : document || anchored ? 'Generate next revision' : 'Generate document'}</button>
    </fieldset>
    {!options.can_generate && <p>Writer or admin access is required to generate and publish documents.</p>}
    {!selected?.available && <p>{selected?.reason || 'The selected provider needs server credentials before it can run.'}</p>}
    {error && <p role="alert">{error}</p>}
    {bothEdited && <div className="docw-actions"><button type="button" disabled={busy} onClick={event => submit(event, true)}>Start from the published copy on GitHub</button></div>}
    {bothEdited && document && <p>The new revision starts from the GitHub text; revision {document.current_revision} stays in the history.</p>}
  </form>;
}

const docPendingEdits = new Map<string, PendingEdit>();
window.addEventListener('beforeunload', event => {
  if (docPendingEdits.size) { event.preventDefault(); event.returnValue = ''; }
});

function DocumentationEditor({ title: initialTitle, body: initialBody, path, expectedRevision, options, onStarted, onCancel }: {
  title: string | null | undefined; body: string; path: string; expectedRevision?: number;
  options: DocumentationOptions; onStarted: (run: DocumentationRun) => void; onCancel: () => void;
}) {
  const [title, setTitle] = React.useState(() => docPendingEdits.get(path)?.title ?? initialTitle ?? '');
  const [body, setBody] = React.useState(() => docPendingEdits.get(path)?.body ?? initialBody);
  const [baseRevision] = React.useState(() => docPendingEdits.get(path)?.expectedRevision ?? expectedRevision);
  const serverModel = (model: DocumentationModelOption) => model.provider !== 'agent';
  const [provider, setProvider] = React.useState(() => options.default_provider === 'agent'
    ? options.models.find(model => serverModel(model) && model.available)?.provider ?? 'claude'
    : options.default_provider);
  const [preview, setPreview] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const submitting = React.useRef(false);
  const dirty = title !== (initialTitle || '') || body !== initialBody;
  React.useEffect(() => {
    if (dirty) docPendingEdits.set(path, { title, body, expectedRevision: baseRevision });
    else docPendingEdits.delete(path);
  }, [path, title, body, baseRevision, dirty]);
  const allowed = options.can_generate && options.models.some(model => serverModel(model) && model.provider === provider && model.available);
  const request = async (save: boolean) => {
    if (submitting.current || !title.trim() || !body.trim()) return;
    submitting.current = true; setBusy(true); setError(null);
    try {
      if (save) {
        const run = await docPost<DocumentationRun>(path, { title, body, provider, ...(baseRevision ? { expected_revision: baseRevision } : {}) });
        docPendingEdits.delete(path); onStarted(run);
      } else {
        const result = await docPost<{ body_html: string }>('preview', { title, body });
        setPreview(result.body_html);
      }
    } catch (error) { setError(errorMessage(error)); }
    finally { submitting.current = false; setBusy(false); }
  };
  return <form className="docw-panel" onSubmit={event => { event.preventDefault(); if (allowed) request(true); }}>
    <h2>Edit document</h2>
    <p>Your Markdown will be checked against the knowledge base and writing profile. Passing review saves the result internally. You can then create a GitHub PR.</p>
    <p>Unsubmitted edits stay available while this page is open, even if you switch sections.</p>
    {baseRevision && <p>This edit is based on revision {baseRevision}.</p>}
    <fieldset disabled={busy}>
      <label>Document title<input required maxLength={300} value={title} onChange={event => setTitle(event.target.value)} /></label>
      <label>Markdown body<textarea className="docw-editor" required maxLength={200000} rows={24} value={body} onChange={event => { setBody(event.target.value); setPreview(null); }} /></label>
      <DocumentationModel options={options} value={provider} onChange={setProvider} filter={serverModel} />
      <div className="docw-actions"><button type="button" onClick={() => request(false)} disabled={!title.trim() || !body.trim()}>Preview</button><button type="submit" disabled={!allowed || !title.trim() || !body.trim()}>{busy ? 'Working…' : 'Review and save'}</button><button type="button" onClick={() => { if (!dirty || window.confirm('Discard your unsaved edits?')) { docPendingEdits.delete(path); onCancel(); } }}>Cancel</button></div>
    </fieldset>
    {error && <p role="alert">{error} Your edits are still here.</p>}
    {preview !== null && <article aria-label="Edited document preview" className="docw-prose" dangerouslySetInnerHTML={{ __html: preview }} />}
  </form>;
}

function DocumentationDelivery({ document, canWrite, onUpdated, onConfigure }: {
  document: DocumentationDocument; canWrite: boolean; onUpdated: () => void; onConfigure: () => void;
}) {
  const [destinations, setDestinations] = React.useState<DocumentationDestination[]>([]);
  const [destination, setDestination] = React.useState(document.delivery_destination || '');
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [retry, setRetry] = React.useState(0);
  const submitting = React.useRef(false);
  React.useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    docGet<{ destinations: DocumentationDestination[] }>('destinations').then(value => { if (!cancelled) setDestinations(value.destinations); }).catch(error => { if (!cancelled) setLoadError(errorMessage(error)); });
    return () => { cancelled = true; };
  }, [retry]);
  const selected = destinations.find(item => item.name === destination);
  const coordinates = document.delivery_coordinates || selected?.coordinates;
  const reference = document.delivery_reference;
  const pullRequest = document.pull_request;
  const publish = async () => {
    if (submitting.current || !destination) return;
    submitting.current = true; setBusy(true); setError(null);
    try {
      await docPost<unknown>(`documents/${encodeURIComponent(document.id)}/delivery`, { destination, expected_revision: document.current_revision });
      onUpdated();
    } catch (error) { setError(errorMessage(error)); }
    finally { submitting.current = false; setBusy(false); }
  };
  return <section className="docw-panel" aria-label="GitHub publication">
    <h2>GitHub publication</h2>
    <p role="status">{docDeliveryStatus(document.delivery_status)}{document.published_revision ? ` · last published revision ${document.published_revision}` : ''}</p>
    {pullRequest && <p className="docw-meta">Pull request #{pullRequest.number} · {docPullRequestState(pullRequest.state)}{pullRequest.refreshed_at ? ` · checked ${docDate(pullRequest.refreshed_at)}` : ''}</p>}
    {typeof reference === 'string' && /^https:\/\//i.test(reference) && <p><a href={reference} target="_blank" rel="noopener noreferrer">Open GitHub pull request{pullRequest ? ` #${pullRequest.number}` : ''} ↗</a></p>}
    <label>GitHub repository<select value={destination} disabled={!canWrite || busy || !!document.delivery_destination} onChange={event => setDestination(event.target.value)}>
      <option value="">Select a repository</option>
      {document.delivery_destination && !destinations.some(item => item.name === document.delivery_destination) && <option value={document.delivery_destination}>{document.delivery_destination} (recorded destination)</option>}
      {destinations.map(item => <option key={item.name}>{item.name}</option>)}
    </select></label>
    {coordinates && <p className="docw-meta">{coordinates.host}/{coordinates.owner}/{coordinates.repo} · base branch {coordinates.base_branch}<br />{document.delivery_path || selected?.path_template}</p>}
    {loadError && <p role="alert">{loadError} <button onClick={() => setRetry(value => value + 1)}>Reload destinations</button></p>}
    {!document.delivery_destination && !destinations.length && !loadError && <p>Add a repository destination in Documentation settings before publishing.</p>}
    <div className="docw-actions"><button onClick={publish} disabled={busy || !canWrite || !destination}>{busy ? 'Publishing…' : error ? 'Retry publication' : 'Create / update GitHub PR'}</button><button onClick={onConfigure}>Configure repositories</button></div>
    <p>Publishes revision {document.current_revision}. Merge and deployment are handled in GitHub. Later updates keep this document’s recorded repository and path.</p>
    {error && <p role="alert">{error} Your internal document is still saved.</p>}
  </section>;
}

const STATEMENT_CHANGES: Record<StatementChange['change'], string> = { edited: 'Edited', deleted: 'Deleted', merged: 'Merged into another statement', no_longer_visible: 'No longer visible to this audience' };

function DocumentationStaleness({ document, options, onStarted }: {
  document: DocumentationDocument; options: DocumentationOptions; onStarted: (run: DocumentationRun) => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const submitting = React.useRef(false);
  const { changes } = document.stale;
  const allowed = options.can_generate && options.models.some(model => model.provider === options.default_provider && model.available);
  const revise = async () => {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setError(null);
    try {
      onStarted(await docPost<DocumentationRun>(`documents/${encodeURIComponent(document.id)}/revisions`, { expected_revision: document.current_revision, provider: options.default_provider, update_sources: true }));
    } catch (error) { setError(errorMessage(error)); }
    finally { submitting.current = false; setBusy(false); }
  };
  return <section className="docw-panel docw-stale" aria-label="Out of date">
    <h2>Out of date</h2>
    <p>{changes.length === 1 ? 'A statement' : `${changes.length} statements`} this revision cites changed after it was reviewed. Revising starts a new revision focused on {changes.length === 1 ? 'that change' : 'these changes'}; it is saved internally for review before you publish.</p>
    <ul>{changes.map(change => {
      const target = change.change === 'merged' ? change.merged_into : change.change === 'deleted' ? null : change.statement_id;
      return <li key={change.statement_id}>
        <span className="docw-meta">{STATEMENT_CHANGES[change.change]} · {target ? <a href={'#/s/' + encodeURIComponent(target)}>{target}</a> : change.statement_id}</span>
        <p>Was: {change.old_text}</p>
        {change.new_text !== null && <p>Now: {change.new_text}</p>}
      </li>;
    })}</ul>
    {options.can_generate && <div className="docw-actions"><button type="button" onClick={revise} disabled={busy || !allowed}>{busy ? 'Starting…' : 'Revise'}</button></div>}
    {error && <p role="alert">{error}</p>}
  </section>;
}

function DocumentationDocument({ id, revision, options, onStarted, refresh, onUpdated }: {
  id: string; revision: string | null; options: DocumentationOptions;
  onStarted: (run: DocumentationRun) => void; refresh: number; onUpdated: () => void;
}) {
  const [data, setData] = React.useState<LoadedDocument | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [retry, setRetry] = React.useState(0);
  const [source, setSource] = React.useState(false);
  const [editing, setEditing] = React.useState(false);
  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    setData(null); setError(null); setEditing(false);
    const path = `documents/${encodeURIComponent(id)}`;
    Promise.all([
      docGet<DocumentationDocument>(path, controller.signal),
      docGet<{ revisions: DocumentationRevisionSummary[] }>(path + '/revisions', controller.signal),
      revision ? docGet<DocumentationRevision>(path + '/revisions/' + encodeURIComponent(revision), controller.signal) : Promise.resolve(null),
    ])
      .then(([current, history, selected]) => { if (!cancelled) setData({ current, history: history.revisions, selected: selected || current }); })
      .catch(error => { if (!cancelled) setError(errorMessage(error)); });
    return () => { cancelled = true; controller.abort(); };
  }, [id, revision, refresh, retry]);
  if (error) return <div role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>Reload document</button></div>;
  if (!data) return <p role="status">Loading document…</p>;
  const { current, history, selected } = data;
  const historical = !!revision && Number(revision) !== current.current_revision;
  const selectedRunId = 'run_id' in selected ? selected.run_id : null;
  if (editing) return <DocumentationEditor key={current.id + ":" + current.current_revision} title={current.title} body={current.body} path={`documents/${encodeURIComponent(id)}/edits`} expectedRevision={current.current_revision} options={options} onStarted={onStarted} onCancel={() => setEditing(false)} />;
  const download = () => {
    const url = URL.createObjectURL(new Blob([selected.body], { type: 'text/markdown;charset=utf-8' }));
    const link = window.document.createElement('a'); link.href = url; link.download = selected.slug + '.md'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <>
    <section className="docw-panel">
      <div className="docw-actions"><button onClick={() => docNavigate({ tab: 'library' })}>← All documents</button><button onClick={onUpdated}>Refresh</button></div>
      <h2>{selected.title}{!historical && current.stale.status === 'out_of_date' && <span className="docw-stale-badge">Out of date</span>}</h2><p className="docw-meta">{selected.guideline_set} · {selected.document_type}{current.audience && <> · <AudienceIdentity audience={current.audience} /></>} · revision {revision || current.current_revision}{current.anchor_entity_id && <> · about <Link to={{ view: 'entity', id: current.anchor_entity_id }}>{docEntityName(current.anchor_entity_id)}</Link></>}</p>
      <label>Revision history<select value={revision || current.current_revision} onChange={event => docNavigate({ document: id, revision: event.target.value })}>{history.map(item => <option key={item.revision} value={item.revision}>Revision {item.revision}{item.revision === current.current_revision ? ' (current)' : ''} · {docDate(item.created_at)}</option>)}</select></label>
      {historical && <p>You are reading an earlier revision. <button onClick={() => docNavigate({ document: id })}>Open current revision to edit or publish</button></p>}
      <div className="docw-actions"><button onClick={() => setSource(value => !value)}>{source ? 'Read document' : 'View Markdown'}</button><button onClick={download}>Download Markdown</button>{!historical && options.can_generate && <button onClick={() => setEditing(true)}>{docPendingEdits.has(`documents/${encodeURIComponent(id)}/edits`) ? 'Resume edit' : 'Edit Markdown'}</button>}</div>
      {source ? <pre className="docw-source">{selected.body}</pre> : <article className="docw-prose" dangerouslySetInnerHTML={{ __html: selected.body_html }} />}
      <details><summary>Sources and review</summary><p>{selected.statement_ids?.length || 0} source statements</p><DocumentationSources ids={selected.statement_ids || []} /><pre className="docw-source">{JSON.stringify(selected.review, null, 2)}</pre></details>
      {(selectedRunId || (!historical && current.last_run_id)) && <p><button onClick={() => docNavigate({ run: selectedRunId || current.last_run_id })}>View generation run</button></p>}
    </section>
    {!historical && current.stale.status === 'out_of_date' && <DocumentationStaleness key={current.current_revision} document={current} options={options} onStarted={onStarted} />}
    {!historical && <><DocumentationDelivery key={current.current_revision} document={current} canWrite={options.can_generate} onUpdated={onUpdated} onConfigure={() => { window.location.hash = '#/settings/documentation'; }} /><DocumentationGenerator key={current.id + ':' + current.current_revision} options={options} document={current} onStarted={onStarted} /></>}
  </>;
}

function DocumentationRun({ id, onCompleted, options, onStarted }: {
  id: string; onCompleted: () => void; options: DocumentationOptions; onStarted: (run: DocumentationRun) => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const [run, setRun] = React.useState<DocumentationRun | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [retry, setRetry] = React.useState(0);
  React.useEffect(() => {
    let cancelled = false, timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    setRun(null); setError(null);
    const load = async () => {
      try {
        const value = await docGet<DocumentationRun>('runs/' + encodeURIComponent(id), controller.signal);
        if (cancelled) return;
        setRun(value); setError(null);
        if (docActive(value)) timer = setTimeout(load, 2500);
        else onCompleted();
      } catch (error) { if (!cancelled) setError(errorMessage(error)); }
    };
    load(); return () => { cancelled = true; controller.abort(); clearTimeout(timer); };
  }, [id, retry, onCompleted]);
  if (error) return <p role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>Reload run</button></p>;
  if (!run) return <p role="status">Loading run…</p>;
  if (editing) return <DocumentationEditor title={run.draft_title} body={run.draft_body || ''} path={`runs/${encodeURIComponent(id)}/edits`} options={options} onStarted={onStarted} onCancel={() => setEditing(false)} />;
  return <section className="docw-panel" aria-label="Generation run"><h2>{docStatus(run)}</h2><p className="docw-meta">{run.provider === 'agent'
    ? <>External agent{run.model !== null && <> · {run.model} · Effort: {run.reasoning_effort ?? 'Model default'}</>}</>
    : <>{run.provider} · {run.model} · Effort: {run.reasoning_effort ?? 'Model default'}</>} · {docDate(run.created_at)}</p><p>{run.prompt}</p>
    {run.target_document_id && <p>Revises <a href={'#/documentation?document=' + encodeURIComponent(run.target_document_id)}>an existing document</a>, starting from its revision {run.target_revision}.</p>}
    {run.revision_base === 'destination' && <p>This revision started from the published copy on GitHub.</p>}
    {run.retry_of && <p>{run.attempt ? `Automatic retry ${run.attempt}` : 'Retry'} of <a href={'#/documentation?run=' + encodeURIComponent(run.retry_of)}>an earlier run</a>.</p>}
    {run.recovery === 'retried' && <p>Retried in a later run.</p>}
    {run.recovery === 'gave_up' && run.recovery_note && <p role="alert">{run.recovery_note}</p>}
    {run.delivery === 'published' && <p>Published automatically after review.</p>}
    {run.delivery === 'failed' && run.delivery_error && <p role="alert">Automatic publication failed: {run.delivery_error}</p>}
    {run.review_notes.length > 0 && <details><summary>Writer briefed with notes from an earlier review</summary><ul>{run.review_notes.map((note, index) => <li key={index}><strong>{REVIEW_CHECKS[note.check]}</strong> · {note.where}: {note.problem}</li>)}</ul></details>}
    {docActive(run) && <p role="status">{run.agent_task ? agentRunStatus(run.agent_task) : <>{run.summary?.activity ? `${run.summary.activity}. ` : ''}You can leave this screen while generation and review finish.</>}</p>}
    {docActive(run) && !!run.agent_task?.findings.length && <details><summary>Last submission refused</summary><ul>{run.agent_task.findings.map((finding, index) => <li key={index}><strong>{finding.check}</strong>{finding.where ? ` · ${finding.where}` : ''}: {finding.problem}</li>)}</ul></details>}
    {run.summary && <DocumentationRunSummary summary={run.summary} />}
    {run.summary?.cited_statement_ids?.length ? <details><summary>Cited statements</summary><DocumentationSources ids={run.summary.cited_statement_ids} /></details> : null}
    {run.summary?.review_findings?.length ? <DocumentationReviewNotes notes={run.summary.review_findings} /> : run.error && <p role="alert">{run.error}</p>}
    {run.retryable && options.can_generate && <DocumentationRetry run={run} onStarted={onStarted} />}
    {run.document_id && <button onClick={() => docNavigate({ document: run.document_id, revision: run.result_revision })}>{run.result_revision ? `Read saved revision ${run.result_revision}` : 'Open document'}</button>}
    {run.document_id && !run.result_revision && <p>This older run has no retained revision snapshot. The link opens the current document.</p>}
    {run.draft_body && !docActive(run) && !run.document_id && options.can_generate && <button onClick={() => setEditing(true)}>{docPendingEdits.has(`runs/${encodeURIComponent(id)}/edits`) ? 'Resume draft edit' : 'Edit and review draft'}</button>}
    {run.draft_body && <details open><summary>Unsaved draft · {run.draft_title}</summary><pre className="docw-source">{run.draft_body}</pre></details>}
  </section>;
}

const REVIEW_CHECKS: Record<ReviewNote['check'], string> = { exposure: 'Not for this audience', conformance: 'Does not follow the template' };

function DocumentationReviewNotes({ notes }: { notes: ReviewNote[] }) {
  return <div role="alert"><p>The review refused this document:</p>
    <ul>{notes.map((note, index) => <li key={index}><strong>{REVIEW_CHECKS[note.check]}</strong> · {note.where}: {note.problem}</li>)}</ul>
  </div>;
}

function DocumentationRetry({ run, onStarted }: { run: DocumentationRun; onStarted: (run: DocumentationRun) => void }) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const retry = async (withReviewNotes: boolean) => {
    setBusy(true); setError(null);
    try { onStarted(await docPost<DocumentationRun>(`runs/${encodeURIComponent(run.id)}/retry`, withReviewNotes ? { with_review_notes: true } : {})); }
    catch (error) { setError(errorMessage(error)); }
    finally { setBusy(false); }
  };
  return <div className="docw-actions">
    {run.summary?.review_findings?.length ? <button disabled={busy} onClick={() => retry(true)}>Retry with these notes</button> : null}
    <button disabled={busy} onClick={() => retry(false)}>Retry</button>
    {error && <p role="alert">{error}</p>}
  </div>;
}

const PLANNING_POLICIES: Record<DocumentationPlan['planning'], string> = { off: 'Planned by hand', propose: 'Plans by itself; items wait for approval', write: 'Plans and writes by itself' };
const PRIORITIES: Record<PlanItem['priority'], string> = { high: 'High priority', medium: 'Medium priority', low: 'Low priority' };
const planActive = (plan: DocumentationPlan) => !!plan.latest && !plan.latest.finished_at;
const WROTE_NOTHING = ['nothing_written', 'failed'];
const planRunning = (plan: DocumentationPlan) => planActive(plan) || plan.items.some(item => item.run && ['queued', 'waiting_for_agent', 'running'].includes(item.run.status));

function DocumentationPlanner({ options, profile }: { options: DocumentationOptions; profile: string | null }) {
  const profiles = Object.keys(options.guideline_sets);
  const selected = profile && profiles.includes(profile) ? profile : profiles[0] || '';
  const [plan, setPlan] = React.useState<DocumentationPlan | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [notes, setNotes] = React.useState<string[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [chosen, setChosen] = React.useState<string[]>([]);
  const [reload, setReload] = React.useState(0);
  const refresh = () => setReload(value => value + 1);
  React.useEffect(() => {
    if (!selected) return;
    let cancelled = false, timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const load = async () => {
      try {
        const value = await docGet<DocumentationPlan>('plans/' + encodeURIComponent(selected), controller.signal);
        if (cancelled) return;
        setPlan(value); setError(null);
        if (planRunning(value)) timer = setTimeout(load, 2500);
      } catch (error) { if (!cancelled) setError(errorMessage(error)); }
    };
    load(); return () => { cancelled = true; controller.abort(); clearTimeout(timer); };
  }, [selected, reload]);
  const act = async (work: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true); setError(null);
    try { await work(); refresh(); } catch (error) { setError(errorMessage(error)); } finally { setBusy(false); }
  };
  const approve = (ids: string[]) => act(async () => {
    const results = await docPost<ApprovedItem[]>('plan-items/approve', { item_ids: ids });
    setChosen([]);
    setNotes(results.filter(result => result.error).map(result => `${plan?.items.find(item => item.id === result.item_id)?.title || result.item_id}: ${result.error}`));
  });
  const reviseStale = (documentId: string, revision: number) => act(() => docPost(`documents/${encodeURIComponent(documentId)}/revisions`, { expected_revision: revision, provider: options.default_provider, update_sources: true }));
  if (!profiles.length) return <section className="docw-panel"><p>Add a writing profile in Settings before planning documentation.</p></section>;
  const latest = plan?.latest;
  const active = !!plan && planActive(plan);
  const proposed = plan?.items.filter(item => item.state === 'proposed') || [];
  const limit = plan?.approve_batch || 1;
  const canAct = options.can_generate && !busy;
  return <>
    <section className="docw-panel" aria-label="Documentation plan">
      <div className="docw-actions"><h2>Plan documentation</h2><button onClick={refresh}>Refresh</button></div>
      <p>The planner reads what the profile's audience may see and proposes the documents that audience needs. Approving an item starts a documentation run; nothing is written before you approve.</p>
      <label>Writing profile<select value={selected} onChange={event => docNavigate({ tab: 'plan', profile: event.target.value })}>{profiles.map(name => <option key={name}>{name}</option>)}</select></label>
      {plan && <p className="docw-meta">{plan.audience ? <>Audience: <AudienceIdentity audience={plan.audience} /> · {plan.visible_statements} visible statements</> : 'No audience'} · {PLANNING_POLICIES[plan.planning]}{plan.plan_review === 'ai' && ' · Items decided by an AI reviewer'}{plan.recovery === 'ai' && ' · Failed AI work is retried'}</p>}
      {plan?.unavailable && <p role="alert">{plan.unavailable}</p>}
      {plan && <div className="docw-actions">
        <button type="button" disabled={!canAct || active || !!plan.unavailable} onClick={() => act(() => docPost('plans/' + encodeURIComponent(selected), {}))}>{active ? 'Planning…' : latest ? 'Plan again' : 'Plan documentation'}</button>
        {latest?.finished_at && (latest.provider === 'agent'
          ? <span className="docw-meta">Last plan made by an external agent</span>
          : latest.tokens !== null && <span className="docw-meta">Last plan used {docTokens(latest.tokens)} tokens · {latest.model}</span>)}
      </div>}
      {active && latest && <p role="status">{latest.agent_task ? agentPlanStatus(latest.agent_task) : <>{latest.activity || 'Planning'}… started {docDate(latest.created_at)}.</>} You can leave this screen; the plan keeps running.</p>}
      {plan?.review_task && <p role="status">Review of the proposed items: {agentPlanStatus(plan.review_task)}</p>}
      {plan?.replan_hint && <p role="status">{plan.new_since_plan} statements became visible to this audience since the last plan. Plan again to consider them.</p>}
      {latest?.outcome === 'failed' && <p role="alert">The last plan failed: {latest.error}</p>}
      {plan?.recovery_note && <p role="status">{plan.recovery_note}</p>}
      {!options.can_generate && <p>Writer or admin access is required to plan and approve documents.</p>}
      {error && <p role="alert">{error}</p>}
      {notes.map(note => <p key={note} role="alert">{note}</p>)}
    </section>
    {plan && <section className="docw-panel" aria-label="Proposed documents">
      <div className="docw-actions"><h2>Proposed documents</h2>
        {proposed.length > 0 && <button type="button" disabled={!canAct || !chosen.length || chosen.length > limit} onClick={() => approve(chosen)}>Approve selected ({chosen.length} of at most {limit})</button>}
      </div>
      {latest?.outcome === 'planned' || plan.items.length ? <p className="docw-meta">{plan.items.length} proposed{latest?.proposed != null && latest.proposed > plan.items.length ? ` · ${latest.proposed - plan.items.length} more set aside (${Object.entries(latest.dropped).map(([reason, count]) => `${count} ${reason}`).join(', ')})` : ''}{plan.dismissed ? ` · ${plan.dismissed} dismissed proposals are not proposed again` : ''}</p> : <p>No plan yet for this profile.</p>}
      <div className="docw-plan">{plan.items.map(item => {
        const checked = chosen.includes(item.id);
        return <article key={item.id} className={'docw-plan-item ' + item.state}>
          {item.state === 'proposed' && options.can_generate && <input type="checkbox" aria-label={'Select ' + item.title} checked={checked} disabled={!checked && chosen.length >= limit} onChange={() => setChosen(value => checked ? value.filter(id => id !== item.id) : [...value, item.id])} />}
          <div>
            <strong>{item.title}</strong>
            <p className="docw-meta">{item.maintenance ? 'Bring up to date' : item.action === 'create' ? 'New' : 'Update'} {item.document_type} · {PRIORITIES[item.priority]}{item.anchor_entity_id && <> · about <Link to={{ view: 'entity', id: item.anchor_entity_id }}>{item.anchor_name || docEntityName(item.anchor_entity_id)}</Link></>}{item.document_id && <> · updates <a href={'#/documentation?document=' + encodeURIComponent(item.document_id)}>the existing document</a></>}</p>
            <p className={item.maintenance ? 'docw-brief' : undefined}>{item.rationale}</p>
            {item.given_up && <p role="status" className="docw-meta">{item.given_up}</p>}
            {item.state === 'proposed' && item.start_error && !item.given_up && <p className="docw-meta">Could not start: {item.start_error}</p>}
            <details><summary>{item.statement_ids.length} {item.maintenance ? 'changed statements' : 'statements it would mainly draw on'}</summary><DocumentationSources ids={item.statement_ids} /></details>
            {item.state === 'proposed' && options.can_generate && <div className="docw-actions"><button type="button" disabled={!canAct} onClick={() => approve([item.id])}>Approve</button><button type="button" disabled={!canAct} onClick={() => act(() => docPost(`plan-items/${encodeURIComponent(item.id)}/dismiss`, {}))}>Dismiss</button></div>}
            {item.review && <p className="docw-meta">{item.review.decision === 'approve' ? 'Approved by AI review' : item.review.decision === 'dismiss' ? 'Dismissed by AI review' : 'Not reviewed'}{item.review.reviewer && <> ({item.review.reviewer})</>}: {item.review.reason}{item.review.decision === 'approve' && item.state === 'proposed' && ' · starts when the active-run limit has room'}</p>}
            {item.state === 'dismissed' && <p className="docw-meta">Dismissed</p>}
            {item.state === 'approved' && <p className="docw-meta">Approved{item.run ? <> · <a href={'#/documentation?run=' + encodeURIComponent(item.run.id)}>{docStatus(item.run)}</a>{item.run.document_id && <> · <a href={'#/documentation?document=' + encodeURIComponent(item.run.document_id)}>open document</a></>}</> : ' · starting'}</p>}
            {item.state === 'approved' && item.run && WROTE_NOTHING.includes(item.run.status) && options.can_generate && <div className="docw-actions">
              {item.run.review_notes && <button type="button" disabled={!canAct} onClick={() => act(() => docPost(`plan-items/${encodeURIComponent(item.id)}/retry`, { with_review_notes: true }))}>Retry with these notes</button>}
              <button type="button" disabled={!canAct} onClick={() => act(() => docPost(`plan-items/${encodeURIComponent(item.id)}/retry`, {}))}>Retry</button>
            </div>}
          </div>
        </article>;
      })}</div>
    </section>}
    {plan && plan.stale.length > 0 && <section className="docw-panel docw-stale" aria-label="Out-of-date documents">
      <h2>Out-of-date documents</h2>
      <p>These documents cite statements that changed. Updating one starts a revision briefed with exactly those changes.</p>
      <div className="docw-plan">{plan.stale.map(item => <article key={item.document_id} className="docw-plan-item">
        <div>
          <strong><a href={'#/documentation?document=' + encodeURIComponent(item.document_id)}>{item.title}</a></strong>
          <p className="docw-meta">Update {item.document_type} · revision {item.revision} · {item.changes.length} changed statements</p>
          <details><summary>What changed</summary><ul>{item.changes.map(change => <li key={change.statement_id}><span className="docw-meta">{STATEMENT_CHANGES[change.change]} · {change.statement_id}</span><p>Was: {change.old_text}</p>{change.new_text !== null && <p>Now: {change.new_text}</p>}</li>)}</ul></details>
          {options.can_generate && <div className="docw-actions"><button type="button" disabled={!canAct} onClick={() => reviseStale(item.document_id, item.revision)}>Approve update</button><button type="button" disabled={!canAct} onClick={() => act(() => docPost(`plans/${encodeURIComponent(selected)}/stale/${encodeURIComponent(item.document_id)}/dismiss`, { revision: item.revision }))}>Dismiss</button></div>}
        </div>
      </article>)}</div>
    </section>}
    {plan && (plan.uncovered_statements > 0 || plan.dismissed_uncovered.length > 0) && <section className="docw-panel" aria-label="Statements without a document">
      <h2>Statements without a document</h2>
      <p>{plan.uncovered_statements} statements this audience may see are cited by no document of this profile. Each plan places up to the limit under Settings → Limits in an existing document or a new one. Dismiss a statement this profile should never document{plan.dismissed_statements ? ` (${plan.dismissed_statements} dismissed)` : ''}.</p>
      <ul>{plan.uncovered.map(statement => <li key={statement.id}><Link to={{ view: 'statement', id: statement.id }}>{statement.text}</Link> <span className="docw-meta">· {statement.kind}</span>
        {options.can_generate && <> <button type="button" disabled={!canAct} onClick={() => act(() => docPost(`plans/${encodeURIComponent(selected)}/uncovered/${encodeURIComponent(statement.id)}/dismiss`, {}))}>Dismiss</button></>}</li>)}</ul>
      {plan.dismissed_uncovered.length > 0 && <details><summary>{plan.dismissed_uncovered.length} dismissed statements</summary><ul>{plan.dismissed_uncovered.map(statement => <li key={statement.id}><Link to={{ view: 'statement', id: statement.id }}>{statement.text}</Link> <span className="docw-meta">· {statement.kind}</span>
        {options.can_generate && <> <button type="button" disabled={!canAct} onClick={() => act(() => docPost(`plans/${encodeURIComponent(selected)}/uncovered/${encodeURIComponent(statement.id)}/restore`, {}))}>Undo dismissal</button></>}</li>)}</ul></details>}
      {plan.uncovered_statements > plan.uncovered.length && <p className="docw-meta">…and {plan.uncovered_statements - plan.uncovered.length} more.</p>}
    </section>}
    {plan && plan.coverage.length > 0 && <section className="docw-panel" aria-label="Coverage">
      <h2>Concepts without a document</h2>
      <p>Concepts this audience sees many statements about, with no document of this profile about them.</p>
      <ul>{plan.coverage.map(gap => <li key={gap.entity_id}><Link to={{ view: 'entity', id: gap.entity_id }}>{gap.name}</Link> <span className="docw-meta">· {gap.statements} visible statements</span></li>)}</ul>
    </section>}
  </>;
}

// The browser remembers when its user last opened Updates; "new" is after that.
const UPDATES_SEEN = 'mycelium.documentation.updates-seen';
const UPDATES_SEEN_EVENT = 'mycelium:documentation-updates-seen';
const needingAttention = (entries: MaintenanceEntry[], seen = localStorage.getItem(UPDATES_SEEN) || '') =>
  entries.filter(entry => entry.waiting || entry.at > seen).length;
const loadDocumentUpdates = () => docGet<{ entries: MaintenanceEntry[] }>('maintenance').then(feed => needingAttention(feed.entries));
const UPDATE_STATES: Record<MaintenanceEntry['state'], string> = {
  proposed: 'Update proposed in the plan', approved: 'Update approved', dismissed: 'Update dismissed', running: 'Revising automatically',
  revised: 'Revised automatically', refused: 'Automatic revision refused by review', failed: 'Automatic revision did not run',
};

function waitingOn(entry: MaintenanceEntry): string | null {
  if (!entry.waiting) return null;
  if (entry.state === 'proposed') return 'Waiting for approval in the plan';
  if (entry.delivery === 'failed') return 'Publishing failed; publish it from the document';
  if (entry.state === 'revised') return 'Pull request waiting for review on GitHub';
  return 'Still out of date; revise it from the document';
}

function DocumentationDiff({ documentId, revision }: { documentId: string; revision: number }) {
  const [diff, setDiff] = React.useState<RevisionDiff | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    const controller = new AbortController();
    docGet<RevisionDiff>(`documents/${encodeURIComponent(documentId)}/revisions/${revision}/diff`, controller.signal)
      .then(setDiff).catch(error => { if (!controller.signal.aborted) setError(errorMessage(error)); });
    return () => controller.abort();
  }, [documentId, revision]);
  if (error) return <p role="alert">{error}</p>;
  if (!diff) return <p role="status">Loading changes…</p>;
  if (!diff.lines.length) return <p>The text did not change.</p>;
  return <pre className="docw-source docw-diff" aria-label={`Revision ${diff.to_revision} against revision ${diff.from_revision}`}>{diff.lines.map((line, index) =>
    <span key={index} className={{ '+': 'add', '-': 'del', '@': 'hunk', ' ': '' }[line.op]}>{line.op === '@' ? line.text : line.op + ' ' + line.text}{'\n'}</span>)}</pre>;
}

function DocumentationUpdates() {
  const [entries, setEntries] = React.useState<MaintenanceEntry[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [reload, setReload] = React.useState(0);
  const [diffs, setDiffs] = React.useState<string[]>([]);
  const [seen] = React.useState(() => localStorage.getItem(UPDATES_SEEN) || '');
  React.useEffect(() => {
    const controller = new AbortController();
    docGet<{ entries: MaintenanceEntry[] }>('maintenance', controller.signal).then(feed => {
      setEntries(feed.entries); setError(null);
      localStorage.setItem(UPDATES_SEEN, new Date().toISOString());
      window.dispatchEvent(new Event(UPDATES_SEEN_EVENT));
    }).catch(error => { if (!controller.signal.aborted) setError(errorMessage(error)); });
    return () => controller.abort();
  }, [reload]);
  return <section className="docw-panel" aria-label="Document updates">
    <div className="docw-actions"><h2>Updates</h2><button onClick={() => setReload(value => value + 1)}>Refresh</button></div>
    <p>Documents of profiles that propose or make their own revisions when a statement they cite changes. Choose the policy per writing profile in Settings → Documentation.</p>
    {error && <p role="alert">{error}</p>}
    {entries && !entries.length && <p>Nothing yet. Documents of manually maintained profiles show as out of date in the library instead.</p>}
    {entries && <div className="docw-plan">{entries.map(entry => {
      const key = `${entry.document_id}:${entry.revision}`;
      const waiting = waitingOn(entry);
      return <article key={key} className="docw-plan-item">
        <div>
          <strong><a href={'#/documentation?document=' + encodeURIComponent(entry.document_id)}>{entry.title}</a></strong>
          {entry.at > seen && <span className="docw-stale-badge">New</span>}
          <p className="docw-meta">{UPDATE_STATES[entry.state]} · {entry.guideline_set} · revision {entry.revision}{entry.new_revision !== null && ` → ${entry.new_revision}`} · {docDate(entry.at)}
            {entry.run_id && <> · <a href={'#/documentation?run=' + encodeURIComponent(entry.run_id)}>run</a></>}
            {entry.pull_request && entry.delivery === 'published' && <> · {entry.pull_request.url ? <a href={entry.pull_request.url} target="_blank" rel="noreferrer">pull request #{entry.pull_request.number}</a> : `pull request #${entry.pull_request.number}`} {docPullRequestState(entry.pull_request.state || '').toLowerCase()}</>}</p>
          {waiting && <p role="status">{waiting}</p>}
          {entry.error && <p role="alert">{entry.error}</p>}
          <details><summary>What changed ({entry.changes.length} {entry.changes.length === 1 ? 'statement' : 'statements'})</summary><ul>{entry.changes.map(change => <li key={change.statement_id}><span className="docw-meta">{STATEMENT_CHANGES[change.change]} · {change.statement_id}</span><p>Was: {change.old_text}</p>{change.new_text !== null && <p>Now: {change.new_text}</p>}</li>)}</ul></details>
          {entry.new_revision !== null && <details onToggle={event => { const open = event.currentTarget.open; setDiffs(value => open ? [...value, key] : value.filter(item => item !== key)); }}>
            <summary>Revision {entry.new_revision} against revision {entry.revision}</summary>
            {diffs.includes(key) && <DocumentationDiff documentId={entry.document_id} revision={entry.new_revision} />}
          </details>}
        </div>
      </article>;
    })}</div>}
  </section>;
}

function DocumentationWorkspace() {
  const [route, setRoute] = React.useState(docRoute);
  const [options, setOptions] = React.useState<DocumentationOptions | null>(null);
  const [documents, setDocuments] = React.useState<DocumentationSummary[]>([]);
  const [runs, setRuns] = React.useState<DocumentationRun[]>([]);
  const [updates, setUpdates] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);
  const [refresh, setRefresh] = React.useState(0);
  const [search, setSearch] = React.useState('');
  const update = React.useCallback(() => setRefresh(value => value + 1), []);
  React.useEffect(() => {
    const change = () => setRoute(docRoute());
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  React.useEffect(() => {
    let cancelled = false, timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    setError(null);
    const load = async () => {
      try {
        const [options, library, history, maintained] = await Promise.all([
          docGet<DocumentationOptions>('options', controller.signal),
          docGet<{ documents: DocumentationSummary[] }>('documents', controller.signal),
          docGet<{ runs: DocumentationRun[] }>('runs', controller.signal),
          docGet<{ entries: MaintenanceEntry[] }>('maintenance', controller.signal),
        ]);
        if (cancelled) return;
        setOptions(options); setDocuments(library.documents); setRuns(history.runs); setUpdates(needingAttention(maintained.entries)); setError(null);
        if (history.runs.some(docActive)) timer = setTimeout(load, 2500);
      } catch (error) { if (!cancelled) setError(errorMessage(error)); }
    };
    load(); return () => { cancelled = true; controller.abort(); clearTimeout(timer); };
  }, [refresh, route.tab]);
  const started = (run: DocumentationRun) => { update(); docNavigate({ run: run.id }); };
  const filtered = documents.filter(document => [document.title, document.guideline_set, document.document_type].join(' ').toLowerCase().includes(search.toLowerCase()));
  return <main className="page docw"><PageHeader eyebrow="Explore" title="Documents" blurb="Generate documents from the knowledge base, refine them, and publish them to GitHub as pull requests."
      actions={<Link to={{ view: 'settings', section: 'documentation' }} className="btn ghost sm">Profiles &amp; publishing settings</Link>} />
    <nav className="tabs" aria-label="Documentation sections">{[['library', 'Documents'], ['updates', updates ? `Updates (${updates})` : 'Updates'], ['plan', 'Plan'], ['generate', 'Generate'], ['runs', 'Generation history']].map(([tab, label]) => <button key={tab} className={route.tab === tab ? 'on' : ''} aria-current={route.tab === tab ? 'page' : undefined} onClick={() => docNavigate({ tab })}>{label}</button>)}</nav>
    {error && <p role="alert">{error} <button onClick={update}>Reload documentation</button></p>}
    {!options ? !error && <p role="status">Loading documentation…</p> : <>
      {route.tab === 'updates' && <DocumentationUpdates />}
      {route.tab === 'plan' && <DocumentationPlanner key={route.profile || ''} options={options} profile={route.profile} />}
      {route.tab === 'generate' && <DocumentationGenerator options={options} documents={documents} onStarted={started} />}
      {route.tab === 'library' && (route.document ? <DocumentationDocument key={route.document} id={route.document} revision={route.revision} options={options} refresh={refresh} onUpdated={update} onStarted={started} /> : <section className="docw-panel">
        <div className="docw-actions"><h2>Saved documents</h2><button onClick={() => docNavigate({ tab: 'generate' })}>Generate document</button><button onClick={update}>Refresh</button></div>
        <p>Documents and their revisions are stored in Mycelium and included in instance backups.</p>
        <label>Find a document<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Title, profile, or template" /></label>
        {!documents.length ? <p>No documents yet. Start with Generate, or configure a writing profile first.</p> : !filtered.length ? <p>No documents match this search.</p> : <div className="docw-list">{filtered.map(document => <button key={document.id} onClick={() => docNavigate({ document: document.id })}><strong>{document.title}</strong><span>{document.guideline_set} · {document.document_type}{document.audience && <> · <AudienceIdentity audience={document.audience} /></>} · revision {document.current_revision}</span><span>{docDeliveryStatus(document.delivery_status)} · updated {docDate(document.updated_at)}</span>{document.stale.status === 'out_of_date' && <span className="docw-stale-badge">Out of date</span>}</button>)}</div>}
      </section>)}
      {route.tab === 'runs' && <>{route.run && <DocumentationRun key={route.run} id={route.run} onCompleted={update} options={options} onStarted={started} />}<section className="docw-panel"><div className="docw-actions"><h2>Recent generation runs</h2><button onClick={update}>Refresh</button></div>{!runs.length ? <p>No runs yet.</p> : <div className="docw-list">{runs.map(run => <button key={run.id} onClick={() => docNavigate({ run: run.id })}><strong>{run.prompt}</strong><span>{docStatus(run)} · {run.provider} · {docDate(run.created_at)}</span>{run.summary && <span>{docActive(run) && run.summary.activity ? run.summary.activity + ' · ' : ''}{docRunLine(run.summary)}</span>}</button>)}</div>}</section></>}
    </>}
  </main>;
}

export { DocumentationWorkspace, loadDocumentUpdates, UPDATES_SEEN_EVENT };
