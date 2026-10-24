// Model choice per AI action, and the automatic draft review.
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Card, LoadError, Loading, Notice } from './lib';
import { HttpError, errorMessage, getJSON, patchJSON, postJSON, type ActionSettings, type CatalogModel, type Effort, type ModelSettings, type Provider, type ProviderStatus } from './api';
import { tokens } from './ai-usage';
import { dataOf, useAsync, useOnSettingsSaved } from './use-async';

export function draftReviewProviderName(provider: string | null | undefined): string {
  return provider === 'claude' ? 'Claude' : provider === 'openai' ? 'GPT (OpenAI)' : provider === 'agent' ? 'External agent' : 'Unknown provider';
}

function ReasoningEffortField({ provider, value, onChange, label = 'Reasoning effort' }: {
  provider: Provider; value: Effort; onChange: (value: Effort) => void; label?: string;
}) {
  const levels = provider === 'claude' ? ['low', 'medium', 'high', 'xhigh', 'max'] : ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'];
  return (
    <label className="field">
      <span>{label}</span>
      <select className="input" value={value ?? ''} onChange={e => onChange(e.target.value || null)}>
        <option value="">Model default</option>
        {levels.map(l => <option key={l} value={l}>{l === 'xhigh' ? 'Extra high' : l[0].toUpperCase() + l.slice(1)}</option>)}
      </select>
      <span className="hint">Supported levels depend on the model. Higher effort can use more tokens and time; limits still apply.</span>
    </label>
  );
}

const ProviderSelect = ({ value, onChange, label }: { value: Provider; onChange: (p: Provider) => void; label: string }) => (
  <label className="field"><span>{label}</span>
    <select className="input" value={value} onChange={e => onChange(e.target.value === 'openai' ? 'openai' : 'claude')}>
      <option value="claude">Claude</option><option value="openai">OpenAI</option>
    </select>
  </label>
);

// Every model choice picks from the admin's catalog. A saved model the catalog no longer lists stays selected until changed.
function ModelSelect({ provider, value, catalog, required, onChange }: {
  provider: Provider; value: string; catalog: CatalogModel[]; required?: boolean; onChange: (model: string) => void;
}) {
  const offered = catalog.filter(m => m.provider === provider).map(m => m.model);
  return (
    <label className="field"><span>Model</span>
      <select className="input" value={value} required={required} onChange={e => onChange(e.target.value)}>
        <option value="">Choose a model</option>
        {value && !offered.includes(value) && <option value={value}>{value} (not in the catalog)</option>}
        {offered.map(m => <option key={m} value={m}>{m}</option>)}
      </select>
      {offered.length === 0 && <span className="hint">Add a {actionProviderName(provider)} model to the model catalog first.</span>}
    </label>
  );
}

// Settings saves are optimistic-locked by revision: a 409 means someone else
// saved first, and the form must be reloaded before it can save again.
function saveError(e: unknown, what: string): { message: string; conflict: boolean } {
  if (e instanceof HttpError && e.status === 409) return { message: `Someone else changed ${what}. Reload the current values before saving again.`, conflict: true };
  return { message: errorMessage(e, `${what} could not be saved.`), conflict: false };
}

/* ============================ per-action models ============================ */
const ACTION_TITLES: Record<string, string> = { ask: 'Questions (Ask)', ingest: 'Ingestion', docgen: 'Document generation', alias_discovery: 'Alias discovery', audience_labelling: 'Audience labelling', documentation_planning: 'Documentation planning', connect: 'Connecting statements' };
type ActionRunner = Provider | 'external';

const actionProviderName = (provider: Provider): string => provider === 'claude' ? 'Claude' : 'OpenAI';

function ActionRunnerSelect({ value, agentSupported, hint, onChange }: { value: ActionRunner; agentSupported: boolean; hint?: string; onChange: (value: ActionRunner) => void }) {
  return (
    <label className="field"><span>Runs on</span>
      <select className="input" value={value} onChange={e => onChange(e.target.value === 'external' ? 'external' : e.target.value === 'openai' ? 'openai' : 'claude')}>
        <option value="claude">Claude</option><option value="openai">OpenAI</option>{agentSupported && <option value="external">External agent</option>}
      </select>
      {hint && <span className="hint">{hint}</span>}
    </label>
  );
}

/* ============================ model catalog ============================ */
interface CatalogSettings { kind: 'model_catalog'; claude: string[]; openai: string[] }
interface CatalogSection { settings: CatalogSettings; revision: number | string; configuration_error?: string | null }

const loadCatalog = async (): Promise<CatalogSection> => {
  const data = await getJSON<{ sections: { settings: { kind: string }; revision: number | string; configuration_error?: string | null }[] }>('/api/product-settings');
  const section = data.sections.find((s): s is CatalogSection => s.settings.kind === 'model_catalog');
  if (!section) throw new Error('The model catalog is unavailable.');
  return section;
};

// The models every picker offers, per provider in the admin's order. Saved as one product-settings section, so a stale
// revision answers 409; removing a model an action uses is refused by the server, naming the actions.
function ModelCatalog({ canConfigure }: { canConfigure: boolean }) {
  const { state, reload } = useAsync(useCallback(() => loadCatalog(), []));
  const section = dataOf(state);
  const [form, setForm] = useState<CatalogSettings | null>(null);
  const [adding, setAdding] = useState<Record<Provider, string>>({ claude: '', openai: '' });
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [seen, setSeen] = useState(section);
  if (section !== seen) { setSeen(section); if (section && (!form || sameForm(form, seen?.settings))) setForm(section.settings); }
  if (!section || !form) return state.status === 'error' ? <LoadError error={state.error} what="the model catalog" onRetry={reload} /> : <Loading what="the model catalog" />;

  const change = (provider: Provider, models: string[]) => { setForm({ ...form, [provider]: models }); setSaved(false); };
  const move = (provider: Provider, index: number, by: number) => {
    const models = [...form[provider]];
    [models[index], models[index + by]] = [models[index + by], models[index]];
    change(provider, models);
  };
  const add = (provider: Provider) => {
    const model = adding[provider].trim();
    if (!model || form[provider].includes(model)) return;
    change(provider, [...form[provider], model]);
    setAdding(a => ({ ...a, [provider]: '' }));
  };
  const save = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError(null); setSaved(false);
    try {
      const value = await patchJSON<CatalogSection>('/api/product-settings', { revision: section.revision, settings: form });
      setForm(value.settings); setSeen(value); setSaved(true); reload();
    } catch (ex) { const r = saveError(ex, 'the model catalog'); setError(r.message); setConflict(r.conflict); }
    finally { setBusy(false); }
  };

  return (
    <Card title="Model catalog" actions={<button type="button" className="btn ghost sm" onClick={() => { setForm(null); setConflict(false); setError(null); reload(); }} disabled={busy}>Reload</button>}>
      <p className="muted">The models every action and the draft reviewer can choose from. The first model of a provider is listed first.</p>
      {section.configuration_error && <Notice tone="error">{section.configuration_error}</Notice>}
      {error && <Notice tone="error">{error}</Notice>}
      <form onSubmit={save}>
        <fieldset disabled={busy || conflict || !canConfigure}>
          <div className="field-grid">
            {(['claude', 'openai'] as const).map(provider => (
              <div key={provider} className="stack-sm">
                <b>{actionProviderName(provider)}</b>
                {form[provider].length === 0 && <p className="hint">No {actionProviderName(provider)} models yet.</p>}
                <ul className="stack-sm">{form[provider].map((model, index) => (
                  <li key={model} className="row gap-sm">
                    <code className="grow">{model}</code>
                    {canConfigure && <>
                      <button type="button" className="btn ghost sm" aria-label={`Move ${model} up`} disabled={index === 0} onClick={() => move(provider, index, -1)}>↑</button>
                      <button type="button" className="btn ghost sm" aria-label={`Move ${model} down`} disabled={index === form[provider].length - 1} onClick={() => move(provider, index, 1)}>↓</button>
                      <button type="button" className="btn ghost sm" aria-label={`Remove ${model}`} onClick={() => change(provider, form[provider].filter(m => m !== model))}>Remove</button>
                    </>}
                  </li>
                ))}</ul>
                {canConfigure && <div className="row gap-sm">
                  <input className="input grow" aria-label={`Add a ${actionProviderName(provider)} model ID`} placeholder="Model ID" maxLength={200} value={adding[provider]}
                    onChange={e => setAdding(a => ({ ...a, [provider]: e.target.value }))}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); add(provider); } }} />
                  <button type="button" className="btn sm" onClick={() => add(provider)} disabled={!adding[provider].trim()}>Add</button>
                </div>}
              </div>
            ))}
          </div>
          {canConfigure && <div className="row gap-sm">
            <button type="submit" className="btn primary" disabled={sameForm(form, section.settings)}>{busy ? 'Saving…' : 'Save catalog'}</button>
            {saved && <span className="ok-text small" role="status">Saved.</span>}
          </div>}
        </fieldset>
      </form>
      {!canConfigure && <p className="hint">Only administrators can change the catalog.</p>}
    </Card>
  );
}

function formOf(s: ActionSettings) {
  return { provider: s.provider, claude_model: s.claude_model, openai_model: s.openai_model, claude_reasoning_effort: s.claude_reasoning_effort ?? null, openai_reasoning_effort: s.openai_reasoning_effort ?? null, external_agent: s.external_agent ?? false, agent_review: s.agent_review ?? 'server', revision: s.revision };
}

const sameForm = <T,>(a: T, b: T) => JSON.stringify(a) === JSON.stringify(b);

function ActionModelSettings({ settings, catalog, canConfigure }: { settings: ActionSettings; catalog: CatalogModel[]; canConfigure: boolean }) {
  const [current, setCurrent] = useState(settings);
  const [form, setForm] = useState(() => formOf(settings));
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const title = ACTION_TITLES[settings.action] || settings.action;
  const claude = form.provider === 'claude';
  const model = claude ? form.claude_model : form.openai_model;
  const effort = claude ? form.claude_reasoning_effort : form.openai_reasoning_effort;
  const needsProvider = !form.external_agent || (settings.action === 'docgen' && form.agent_review === 'server');
  const showProvider = !form.external_agent || (settings.action === 'docgen' && form.agent_review === 'server');
  const available = current.providers.find(p => p.provider === form.provider);
  const accept = (value: ActionSettings) => { setCurrent(value); setForm(formOf(value)); };
  // A save elsewhere reloads the list; take its value unless this form has edits.
  const [seen, setSeen] = useState(settings);
  if (settings !== seen) {
    setSeen(settings);
    if (settings.revision !== current.revision && sameForm(form, formOf(current))) accept(settings);
  }
  const edit = (patch: Partial<ReturnType<typeof formOf>>) => { setForm(f => ({ ...f, ...patch })); setSaved(false); };

  const reload = async () => {
    setBusy(true); setError(null); setSaved(false);
    try {
      const data = await getJSON<ModelSettings>('/api/model-settings');
      const value = data.actions.find(a => a.action === settings.action);
      if (!value) throw new Error('These model settings are unavailable.');
      accept(value); setConflict(false);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };
  const save = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError(null); setSaved(false);
    try {
      accept(await patchJSON<ActionSettings>(`/api/model-settings/${settings.action}`, form));
      setSaved(true);
    } catch (ex) { const r = saveError(ex, `the ${title.toLowerCase()} model`); setError(r.message); setConflict(r.conflict); }
    finally { setBusy(false); }
  };

  return (
    <Card title={title} actions={<button type="button" className="btn ghost sm" onClick={() => void reload()} disabled={busy}>Reload</button>}>
      <p className="muted">
        Now: Runs on {current.external_agent
          ? <>External agent{settings.action === 'docgen' && <> · {current.agent_review === 'agent' ? 'reviewed by another agent' : <>reviewed by {actionProviderName(current.provider)} · {current.model}</>}</>}</>
          : <>{actionProviderName(current.provider)} · {current.model || 'no model chosen'} · effort {(current.provider === 'claude' ? current.claude_reasoning_effort : current.openai_reasoning_effort) ?? 'model default'}</>}
      </p>
      {settings.action === 'docgen' && <p className="hint">The default for new documents. Choosing another provider when generating uses that provider's saved model and effort.</p>}
      {current.configuration_error && <Notice tone="error">{current.configuration_error} Save valid settings to enable this action.</Notice>}
      {current.model_warning && <Notice tone="warn">{current.model_warning}</Notice>}
      {error && <Notice tone="error">{error}</Notice>}
      {canConfigure ? (
        <form onSubmit={save}>
          <fieldset disabled={busy || conflict}>
            <div className="field-grid">
              <ActionRunnerSelect value={form.external_agent ? 'external' : form.provider} agentSupported={current.agent_supported === true} hint={form.external_agent ? settings.action === 'ask'
                  ? 'Ask runs no model on the server. People ask their own agent, connected over MCP, which researches with the read tools (mycelium-research skill). Ask is hidden in this web app and from the MCP tool list.'
                  : 'Agents with a writer token claim this work over MCP (claim_agent_task). See Agent tasks in the docs.' : undefined} onChange={value => edit(value === 'external' ? { external_agent: true } : { provider: value, external_agent: false })} />
              {settings.action === 'docgen' && form.external_agent && <label className="field"><span>Review</span>
                <select className="input" value={form.agent_review} onChange={e => edit({ agent_review: e.target.value === 'agent' ? 'agent' : 'server' })}>
                  <option value="server">Server reviewer (the provider below)</option><option value="agent">Another agent</option>
                </select>
                <span className="hint">Another agent is never the document's writer, but two tokens of one person are not told apart.</span>
              </label>}
              {showProvider && <>
                {form.external_agent && <ProviderSelect value={form.provider} onChange={provider => edit({ provider })} label="Reviewer provider" />}
                <ModelSelect provider={form.provider} value={model} catalog={catalog} required onChange={m => edit(claude ? { claude_model: m } : { openai_model: m })} />
                <ReasoningEffortField provider={form.provider} value={effort} onChange={v => edit(claude ? { claude_reasoning_effort: v } : { openai_reasoning_effort: v })} />
              </>}
            </div>
            {showProvider && <p className="hint">{available?.available ? 'Credentials for this provider are configured on the server.' : available?.reason || 'This provider has no credentials on the server.'}</p>}
            <div className="row gap-sm">
              <button type="submit" className="btn primary" disabled={needsProvider && !model}>{busy ? 'Saving…' : 'Save'}</button>
              {saved && <span className="ok-text small" role="status">Saved. New runs use it.</span>}
            </div>
          </fieldset>
        </form>
      ) : <p className="hint">Only administrators can change this model.</p>}
    </Card>
  );
}

export function ActionModels() {
  const { state, reload } = useAsync(useCallback(() => getJSON<ModelSettings>('/api/model-settings'), []));
  useOnSettingsSaved(reload);
  const data = dataOf(state);
  if (!data) return state.status === 'error' ? <LoadError error={state.error} what="model settings" onRetry={reload} /> : <Loading what="model settings" />;
  const actions = data.actions.filter(a => a.action !== 'draft_review');
  return <>
    <p className="muted">Each action runs independently on Claude, OpenAI or an External agent. Changing one action does not change the others. Saved choices apply to new runs. API credentials stay on the server; model access is checked when a run starts. The draft reviewer's model is under Draft review.</p>
    <ModelCatalog canConfigure={data.can_configure} />
    <Card title="Overview"><table className="tbl compact">
        <thead><tr><th>Action</th><th>Runs on</th><th>Model</th></tr></thead>
        <tbody>{actions.map(action => (
          <tr key={action.action}>
            <td>{ACTION_TITLES[action.action] || action.action}</td>
            <td>{action.external_agent ? 'External agent' : actionProviderName(action.provider)}</td>
            <td>{action.external_agent
              ? action.action === 'docgen' && action.agent_review === 'server' ? <>reviewed by {actionProviderName(action.provider)} · {action.model}</> : '—'
              : action.model || 'none chosen'}</td>
          </tr>
        ))}</tbody>
      </table></Card>
    {actions.map(a => <ActionModelSettings key={a.action} settings={a} catalog={data.catalog} canConfigure={data.can_configure} />)}
  </>;
}

/* ============================ automatic draft review ============================ */
type ReviewMode = 'off' | 'review-only' | 'review-and-apply';
type AutoApply = 'clean' | 'with_corrections';
interface Reviewer { id: string; name: string; role: string }
interface ReviewConfig {
  mode: ReviewMode; application_enabled: boolean; alias_decisions: boolean; answer_questions: boolean; reject_refused: boolean; auto_apply: AutoApply; provider: Provider; model: string; reasoning_effort?: Effort;
  claude_model: string; openai_model: string; claude_reasoning_effort?: Effort; openai_reasoning_effort?: Effort;
  reviewer_id: string; external_agent: boolean; revision: number | string; model_revision: number | string;
  source: string; issues: string[]; model_warning?: string | null; can_configure: boolean; providers: ProviderStatus[]; reviewers: Reviewer[];
  catalog: CatalogModel[];
}
interface ReviewForm { application_enabled: boolean; alias_decisions: boolean; answer_questions: boolean; reject_refused: boolean; auto_apply: AutoApply; mode: ReviewMode; provider: Provider; model: string; reasoning_effort: Effort; reviewer_id: string; external_agent: boolean; revision: number | string; model_revision: number | string }

function reviewForm(d: ReviewConfig): ReviewForm {
  return {
    application_enabled: d.application_enabled, alias_decisions: d.alias_decisions, answer_questions: d.answer_questions, reject_refused: d.reject_refused, auto_apply: d.auto_apply, mode: d.mode, provider: d.provider, model: d.model,
    reasoning_effort: (d.provider === 'claude' ? d.claude_reasoning_effort : d.openai_reasoning_effort) ?? null,
    reviewer_id: d.reviewer_id, external_agent: d.external_agent, revision: d.revision, model_revision: d.model_revision,
  };
}
const MODE_LABEL: Record<ReviewMode, string> = { off: 'Off', 'review-only': 'Review only', 'review-and-apply': 'Review and apply' };
const AUTO_APPLY_LABEL: Record<AutoApply, string> = { clean: 'Only clean approvals', with_corrections: 'Approvals with corrections too' };

interface BacklogJob {
  status: 'running' | 'paused' | 'finished'; used_tokens: number; reviewed: number; remaining: number;
  detail: string | null; started_at: string; finished_at: string | null;
}
interface Backlog { draft_ids: string[]; external_agent: boolean; job: BacklogJob | null }

export function DraftReviewSettings() {
  const { state, reload } = useAsync(useCallback(() => getJSON<ReviewConfig>('/api/draft-review/settings'), []));
  useOnSettingsSaved(reload);
  const data = dataOf(state);
  if (!data) return state.status === 'error' ? <LoadError error={state.error} what="draft review settings" onRetry={reload} /> : <Loading what="draft review settings" />;
  return <DraftReviewForm initial={data} onReload={reload} />;
}

// Drafts submitted while review was off are not reviewed retroactively. An
// admin can run their sequential review as a pausable job.
function BacklogOffer() {
  const load = useCallback((signal: AbortSignal) => getJSON<Backlog>('/api/draft-review/backlog', signal), []);
  const { state, reload, update } = useAsync(load);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const data = dataOf(state);
  const job = data?.job;
  const running = job?.status === 'running';
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(reload, 5000);
    return () => clearInterval(timer);
  }, [running, reload]);

  const start = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setError(null);
    try {
      const result = await postJSON<{ job: BacklogJob }>('/api/draft-review/backlog');
      update(current => ({ ...current, job: result.job }));
    }
    catch (e) { setError(errorMessage(e)); reload(); }
    finally { setBusy(false); }
  };
  const pause = async () => {
    setBusy(true); setError(null);
    try {
      const result = await postJSON<{ job: BacklogJob }>('/api/draft-review/backlog/pause');
      update(current => ({ ...current, job: result.job }));
    } catch (e) { setError(errorMessage(e)); reload(); }
    finally { setBusy(false); }
  };
  const resume = async () => {
    setBusy(true); setError(null);
    try {
      const result = await postJSON<{ job: BacklogJob }>('/api/draft-review/backlog/resume');
      update(current => ({ ...current, job: result.job }));
    } catch (e) { setError(errorMessage(e)); reload(); }
    finally { setBusy(false); }
  };

  if (!data) return null;
  const external = data.external_agent;
  const used = external ? '' : `, ${tokens(job?.used_tokens ?? 0)} tokens used`;
  const progress = job && `${job.status === 'paused' ? 'Backlog review paused' : external ? 'Queuing the backlog for an external agent, oldest first' : 'Reviewing the backlog oldest-first'}: ${job.reviewed} ${external ? 'queued' : 'reviewed'}, ${job.remaining} remaining${used}.`;
  if (job?.status === 'running') return <Notice><div className="stack-sm"><div>{progress}</div><div><button className="btn sm" disabled={busy} onClick={() => void pause()}>{busy ? 'Pausing…' : 'Pause'}</button></div>{error && <p className="form-error">{error}</p>}</div></Notice>;
  if (job?.status === 'paused') return <Notice tone="warn"><div className="stack-sm"><div>{progress}</div>{job.detail && <div>{job.detail}</div>}<div><button className="btn primary sm" disabled={busy} onClick={() => void resume()}>{busy ? 'Resuming…' : 'Resume'}</button></div>{error && <p className="form-error">{error}</p>}</div></Notice>;

  const n = data.draft_ids.length;
  const lastResult = job?.status === 'finished' && <p className="muted small">Last backlog review: {external ? 'queued' : 'reviewed'} {job.reviewed} draft{job.reviewed === 1 ? '' : 's'}{used}.{job.detail && <> {job.detail}</>}</p>;
  if (n === 0) return lastResult || null;
  return (
    <Notice tone="warn">
      <div className="stack-sm">
        {lastResult}
        <div><b>{n} submitted draft{n === 1 ? ' is' : 's are'} waiting from before review was on.</b> {n === 1 ? 'It is' : 'They are'} not reviewed automatically. Review {n === 1 ? 'it' : 'them'} now under these settings?</div>
        <form className="stack-sm" onSubmit={start}>
          <div className="row gap-sm"><button type="submit" className="btn primary sm" disabled={busy}>{busy ? 'Starting…' : `Review ${n} waiting draft${n === 1 ? '' : 's'}`}</button>{external && <span className="hint">Each draft is queued for an external agent to claim.</span>}</div>
          {error && <p className="form-error">{error}</p>}
        </form>
      </div>
    </Notice>
  );
}

function DraftReviewForm({ initial, onReload }: { initial: ReviewConfig; onReload: () => void }) {
  const [settings, setSettings] = useState(initial);
  const [form, setForm] = useState(() => reviewForm(initial));
  const [reviewers, setReviewers] = useState(settings.reviewers);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [accountName, setAccountName] = useState('');
  const [backlogCheck, setBacklogCheck] = useState(0);
  const change = (patch: Partial<ReviewForm>) => { setForm(f => ({ ...f, ...patch })); setSaved(false); };
  // A save elsewhere reloads the settings; take them unless this form has
  // edits. Reload takes them regardless.
  const [seen, setSeen] = useState(initial);
  const [reloading, setReloading] = useState(false);
  if (initial !== seen) {
    setSeen(initial);
    const changed = initial.revision !== settings.revision || initial.model_revision !== settings.model_revision;
    if (reloading || (changed && sameForm(form, reviewForm(settings)))) {
      setSettings(initial); setForm(reviewForm(initial)); setReviewers(initial.reviewers);
      setReloading(false); setConflict(false); setError(null); setSaved(false);
    }
  }
  const reload = () => { setReloading(true); onReload(); };

  const provider = settings.providers.find(p => p.provider === form.provider);
  const reviewerExists = reviewers.some(r => r.id === form.reviewer_id);
  const incomplete = form.mode !== 'off' && !form.external_agent && (!form.model || !reviewerExists || !provider?.available);

  const save = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError(null); setSaved(false);
    try {
      const value = await patchJSON<ReviewConfig>('/api/draft-review/settings', form);
      setSettings(value); setForm(reviewForm(value)); setSaved(true); setBacklogCheck(n => n + 1);
    } catch (ex) { const r = saveError(ex, 'the review settings'); setError(r.message); setConflict(r.conflict); }
    finally { setBusy(false); }
  };
  const createReviewer = async () => {
    setBusy(true); setError(null);
    try {
      const { user } = await postJSON<{ user: Reviewer }>('/api/admin/users', { name: accountName.trim(), role: 'writer', type: 'service' });
      setReviewers(r => [...r, user]); change({ reviewer_id: user.id }); setAccountName('');
    } catch (ex) { setError(errorMessage(ex, 'The reviewer account could not be created.')); }
    finally { setBusy(false); }
  };

  return (
    <Card title="Automatic draft review" actions={<button type="button" className="btn ghost sm" onClick={reload} disabled={busy}>Reload</button>}>
      <p className="muted">
        Now: {MODE_LABEL[settings.mode]}{settings.mode === 'review-and-apply' ? ` (${AUTO_APPLY_LABEL[settings.auto_apply].toLowerCase()})` : ''} · {settings.external_agent ? 'External agent' : `${draftReviewProviderName(settings.provider)} · ${settings.model || 'no model chosen'} · effort ${settings.reasoning_effort ?? 'model default'}`}.
        {' '}Applying accepted reviews is <b>{settings.application_enabled ? 'allowed' : 'not allowed'}</b>; that permission covers both a curator applying a review and automatic application.
      </p>
      {settings.can_configure && settings.mode !== 'off' && <BacklogOffer key={backlogCheck} />}
      {settings.issues.length > 0 && <Notice tone="warn"><ul>{settings.issues.map(i => <li key={i}>{i}</li>)}</ul></Notice>}
      {settings.model_warning && <Notice tone="warn">{settings.model_warning}</Notice>}
      {error && <Notice tone="error">{error}</Notice>}
      {settings.can_configure ? (
        <form onSubmit={save}>
          <fieldset disabled={busy || conflict}>
            <label className="check"><input type="checkbox" checked={form.application_enabled} onChange={e => change({ application_enabled: e.target.checked })} />Allow applying accepted reviews</label>
            <p className="hint">Automatic application also needs Review and apply mode. The permission can be on while reviews are off.</p>
            <label className="check"><input type="checkbox" checked={form.alias_decisions} onChange={e => change({ alias_decisions: e.target.checked })} />Reviewer decides alias suggestions</label>
            <p className="hint">Accepts or rejects each suggestion with a quote from its source; off leaves them to people.</p>
            <label className="check"><input type="checkbox" checked={form.answer_questions} onChange={e => change({ answer_questions: e.target.checked })} />AI answers the reviewer's questions from the knowledge base</label>
            <p className="hint">Used only when a server model reviews drafts; External agent reviews leave questions to people and curation agents.</p>
            <label className="check"><input type="checkbox" checked={form.reject_refused} onChange={e => change({ reject_refused: e.target.checked })} />Reject drafts the server refuses before review (External agent)</label>
            <div className="field-grid">
              <label className="field"><span>Review mode</span>
                <select className="input" value={form.mode} onChange={e => change({ mode: e.target.value as ReviewMode })}>
                  {(Object.keys(MODE_LABEL) as ReviewMode[]).map(m => <option key={m} value={m}>{MODE_LABEL[m]}</option>)}
                </select>
              </label>
              <label className="field"><span>Apply automatically</span>
                <select className="input" value={form.auto_apply} onChange={e => change({ auto_apply: e.target.value as AutoApply })}>
                  {(Object.keys(AUTO_APPLY_LABEL) as AutoApply[]).map(a => <option key={a} value={a}>{AUTO_APPLY_LABEL[a]}</option>)}
                </select>
                <span className="hint">With only clean approvals, a draft the reviewer wants to correct waits for a curator, who applies or edits the suggested corrections.</span>
              </label>
              <ActionRunnerSelect value={form.external_agent ? 'external' : form.provider} agentSupported
                hint={form.external_agent ? 'Agents with a writer token claim reviews over MCP (claim_agent_task, kind draft_review) and act as the reviewer; never of a draft they created.' : undefined}
                onChange={p => change(p === 'external' ? { external_agent: true } : {
                  external_agent: false,
                  provider: p,
                  model: p === 'claude' ? settings.claude_model : settings.openai_model,
                  reasoning_effort: (p === 'claude' ? settings.claude_reasoning_effort : settings.openai_reasoning_effort) ?? null,
                })} />
              {!form.external_agent && <>
              <ModelSelect provider={form.provider} value={form.model} catalog={settings.catalog} required={form.mode !== 'off'} onChange={model => change({ model })} />
              <ReasoningEffortField provider={form.provider} value={form.reasoning_effort} onChange={v => change({ reasoning_effort: v })} />
              <label className="field"><span>Reviewer account</span>
                <select className="input" value={form.reviewer_id} required={form.mode !== 'off'} onChange={e => change({ reviewer_id: e.target.value })}>
                  <option value="">Select an active writer or administrator</option>
                  {form.reviewer_id && !reviewerExists && <option value={form.reviewer_id}>Unavailable account ({form.reviewer_id})</option>}
                  {reviewers.map(u => <option key={u.id} value={u.id}>{u.name} ({u.role})</option>)}
                </select>
                <span className="hint">The reviewer acts as a stored, active writer or administrator, also when authentication is off.</span>
              </label>
              </>}
            </div>
            {!form.external_agent && <>
            <p className="hint">{provider?.available ? 'Provider credentials are configured on the server; model access is checked when a review runs.' : provider?.reason || 'This provider has no credentials on the server.'} API credentials are never stored in this form.</p>
            <details className="disclosure">
              <summary>Create a reviewer account</summary>
              <p className="hint">A service account with the writer role for internal reviews. It needs no access token. Save the review settings afterwards to use it.</p>
              <div className="row gap-sm">
                <input className="input grow" aria-label="Reviewer account name" placeholder="Account name" value={accountName} maxLength={80} onChange={e => setAccountName(e.target.value)} />
                <button type="button" className="btn" onClick={() => void createReviewer()} disabled={!accountName.trim()}>Create account</button>
              </div>
            </details>
            </>}
            <p className="hint">Changes apply to new submissions and reruns. Reviews already running can finish but will not apply automatically after a change.</p>
            {incomplete && <Notice tone="warn">Choose a model, a reviewer account and a provider with server credentials before turning reviews on. Saving Off always works.</Notice>}
            <div className="row gap-sm">
              <button type="submit" className="btn primary" disabled={incomplete}>{busy ? 'Saving…' : 'Save review settings'}</button>
              {saved && <span className="ok-text small" role="status">Saved.</span>}
            </div>
          </fieldset>
        </form>
      ) : <p className="hint">Only administrators can change these settings. Writers can still run or rerun reviews from a draft.</p>}
    </Card>
  );
}
