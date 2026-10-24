// Model choice per AI action, and the automatic draft review.
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Card, LoadError, Loading, Notice } from './lib';
import { HttpError, errorMessage, getJSON, patchJSON, postJSON } from './api';
import { usd } from './ai-usage';
import { dataOf, useAsync, useOnSettingsSaved } from './use-async';

type Provider = 'claude' | 'openai';
type Effort = string | null;
interface ProviderStatus { provider: Provider; available: boolean; reason?: string | null }

export function draftReviewProviderName(provider: string | null | undefined): string {
  return provider === 'claude' ? 'Claude' : provider === 'openai' ? 'GPT (OpenAI)' : 'Unknown provider';
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
      <option value="claude">Claude (Anthropic)</option><option value="openai">GPT (OpenAI)</option>
    </select>
  </label>
);

// Settings saves are optimistic-locked by revision: a 409 means someone else
// saved first, and the form must be reloaded before it can save again.
function saveError(e: unknown, what: string): { message: string; conflict: boolean } {
  if (e instanceof HttpError && e.status === 409) return { message: `Someone else changed ${what}. Reload the current values before saving again.`, conflict: true };
  return { message: errorMessage(e, `${what} could not be saved.`), conflict: false };
}

/* ============================ per-action models ============================ */
interface ActionSettings {
  action: string; provider: Provider; model: string; source: string; revision: number | string;
  claude_model: string; openai_model: string; claude_reasoning_effort?: Effort; openai_reasoning_effort?: Effort;
  configuration_error?: string | null; model_warning?: string | null; providers: ProviderStatus[];
}
interface ModelSettings { can_configure: boolean; actions: ActionSettings[] }
const ACTION_TITLES: Record<string, string> = { ask: 'Questions (Ask)', ingest: 'Ingestion', docgen: 'Document generation', alias_discovery: 'Alias discovery', audience_labelling: 'Audience labelling', documentation_planning: 'Documentation planning', connect: 'Connecting statements' };

function formOf(s: ActionSettings) {
  return { provider: s.provider, claude_model: s.claude_model, openai_model: s.openai_model, claude_reasoning_effort: s.claude_reasoning_effort ?? null, openai_reasoning_effort: s.openai_reasoning_effort ?? null, revision: s.revision };
}

const sameForm = <T,>(a: T, b: T) => JSON.stringify(a) === JSON.stringify(b);

function ActionModelSettings({ settings, canConfigure }: { settings: ActionSettings; canConfigure: boolean }) {
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
      accept(await patchJSON<ActionSettings>(`/api/model-settings/${settings.action}`, { ...form, claude_model: form.claude_model.trim(), openai_model: form.openai_model.trim() }));
      setSaved(true);
    } catch (ex) { const r = saveError(ex, `the ${title.toLowerCase()} model`); setError(r.message); setConflict(r.conflict); }
    finally { setBusy(false); }
  };

  return (
    <Card title={title} actions={<button type="button" className="btn ghost sm" onClick={() => void reload()} disabled={busy}>Reload</button>}>
      <p className="muted">
        Now: {draftReviewProviderName(current.provider)} · {current.model || 'no model configured'} · effort {(current.provider === 'claude' ? current.claude_reasoning_effort : current.openai_reasoning_effort) ?? 'model default'} · {current.source === 'saved' ? 'saved here' : 'built-in default'}
      </p>
      {settings.action === 'docgen' && <p className="hint">The default for new documents. Choosing another provider when generating uses that provider's saved model and effort.</p>}
      {current.configuration_error && <Notice tone="error">{current.configuration_error} Save valid settings to enable this action.</Notice>}
      {current.model_warning && <Notice tone="warn">{current.model_warning}</Notice>}
      {error && <Notice tone="error">{error}</Notice>}
      {canConfigure ? (
        <form onSubmit={save}>
          <fieldset disabled={busy || conflict}>
            <div className="field-grid">
              <ProviderSelect value={form.provider} onChange={provider => edit({ provider })} label="Provider" />
              <label className="field"><span>Model ID</span>
                <input className="input" required value={model} placeholder="A model ID for this provider" onChange={e => edit(claude ? { claude_model: e.target.value } : { openai_model: e.target.value })} />
              </label>
              <ReasoningEffortField provider={form.provider} value={effort} onChange={v => edit(claude ? { claude_reasoning_effort: v } : { openai_reasoning_effort: v })} />
            </div>
            <p className="hint">{available?.available ? 'Credentials for this provider are configured on the server.' : available?.reason || 'This provider has no credentials on the server.'}</p>
            <div className="row gap-sm">
              <button type="submit" className="btn primary" disabled={!model.trim()}>{busy ? 'Saving…' : 'Save'}</button>
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
  return <>
    <p className="muted">Each action picks its provider and model independently. Saved choices apply to new runs. API credentials stay on the server; model access is checked when a run starts. The draft reviewer's model is under Draft review.</p>
    {data.actions.filter(a => a.action !== 'draft_review').map(a => <ActionModelSettings key={a.action} settings={a} canConfigure={data.can_configure} />)}
  </>;
}

/* ============================ automatic draft review ============================ */
type ReviewMode = 'off' | 'review-only' | 'review-and-apply';
interface Reviewer { id: string; name: string; role: string }
interface ReviewConfig {
  mode: ReviewMode; application_enabled: boolean; provider: Provider; model: string; reasoning_effort?: Effort;
  claude_model: string; openai_model: string; claude_reasoning_effort?: Effort; openai_reasoning_effort?: Effort;
  reviewer_id: string; revision: number | string; model_revision: number | string;
  source: string; issues: string[]; model_warning?: string | null; can_configure: boolean; providers: ProviderStatus[]; reviewers: Reviewer[];
}
interface ReviewForm { application_enabled: boolean; mode: ReviewMode; provider: Provider; model: string; reasoning_effort: Effort; reviewer_id: string; revision: number | string; model_revision: number | string }

function reviewForm(d: ReviewConfig): ReviewForm {
  return {
    application_enabled: d.application_enabled, mode: d.mode, provider: d.provider, model: d.model,
    reasoning_effort: (d.provider === 'claude' ? d.claude_reasoning_effort : d.openai_reasoning_effort) ?? null,
    reviewer_id: d.reviewer_id, revision: d.revision, model_revision: d.model_revision,
  };
}
const MODE_LABEL: Record<ReviewMode, string> = { off: 'Off', 'review-only': 'Review only', 'review-and-apply': 'Review and apply' };

interface BacklogJob {
  status: 'running' | 'paused' | 'finished'; budget_usd: number | null; spent_usd: number; reviewed: number; remaining: number;
  detail: string | null; started_at: string; finished_at: string | null;
}
interface Backlog { draft_ids: string[]; estimated_cost_usd: number | null; job: BacklogJob | null }

export function DraftReviewSettings() {
  const { state, reload } = useAsync(useCallback(() => getJSON<ReviewConfig>('/api/draft-review/settings'), []));
  useOnSettingsSaved(reload);
  const data = dataOf(state);
  if (!data) return state.status === 'error' ? <LoadError error={state.error} what="draft review settings" onRetry={reload} /> : <Loading what="draft review settings" />;
  return <DraftReviewForm initial={data} onReload={reload} />;
}

// Drafts submitted while review was off are not reviewed retroactively. An
// admin can run their sequential review as a pausable, budget-aware job.
function BacklogOffer() {
  const load = useCallback((signal: AbortSignal) => getJSON<Backlog>('/api/draft-review/backlog', signal), []);
  const { state, reload, update } = useAsync(load);
  const [budget, setBudget] = useState('');
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
      const result = await postJSON<{ job: BacklogJob }>('/api/draft-review/backlog', { budget_usd: budget === '' ? null : Number(budget) });
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
  const progress = job && `${job.status === 'paused' ? 'Backlog review paused' : 'Reviewing the backlog oldest-first'}: ${job.reviewed} reviewed, ${job.remaining} remaining, about ${usd(job.spent_usd)} spent${job.budget_usd === null ? '' : ` of ${usd(job.budget_usd)}`}.`;
  if (job?.status === 'running') return <Notice><div className="stack-sm"><div>{progress}</div><div><button className="btn sm" disabled={busy} onClick={() => void pause()}>{busy ? 'Pausing…' : 'Pause'}</button></div>{error && <p className="form-error">{error}</p>}</div></Notice>;
  if (job?.status === 'paused') return <Notice tone="warn"><div className="stack-sm"><div>{progress}</div>{job.detail && <div>{job.detail}</div>}<div><button className="btn primary sm" disabled={busy} onClick={() => void resume()}>{busy ? 'Resuming…' : 'Resume'}</button></div>{error && <p className="form-error">{error}</p>}</div></Notice>;

  const n = data.draft_ids.length, cost = data.estimated_cost_usd;
  const lastResult = job?.status === 'finished' && <p className="muted small">Last backlog review: reviewed {job.reviewed} draft{job.reviewed === 1 ? '' : 's'}, spent about {usd(job.spent_usd)}.{job.detail && <> {job.detail}</>}</p>;
  if (n === 0) return lastResult || null;
  return (
    <Notice tone="warn">
      <div className="stack-sm">
        {lastResult}
        <div><b>{n} submitted draft{n === 1 ? ' is' : 's are'} waiting from before review was on.</b> {n === 1 ? 'It is' : 'They are'} not reviewed automatically. Review {n === 1 ? 'it' : 'them'} now under these settings?</div>
        <form className="stack-sm" onSubmit={start}>
          <label className="field"><span>Stop after spending (USD)</span><input className="input" type="number" min="0.01" step="any" value={budget} onChange={e => setBudget(e.target.value)} /></label>
          <div className="row gap-sm"><button type="submit" className="btn primary sm" disabled={busy}>{busy ? 'Starting…' : `Review ${n} waiting draft${n === 1 ? '' : 's'}${cost === null ? '' : ` (about ${usd(cost)})`}`}</button>{cost === null && <span className="hint">Cost not estimated: no priced review in the last 30 days.</span>}</div>
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
  const incomplete = form.mode !== 'off' && (!form.model.trim() || !reviewerExists || !provider?.available);

  const save = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError(null); setSaved(false);
    try {
      const value = await patchJSON<ReviewConfig>('/api/draft-review/settings', { ...form, model: form.model.trim() });
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
        Now: {MODE_LABEL[settings.mode]} · {draftReviewProviderName(settings.provider)} · {settings.model || 'no model configured'} · effort {settings.reasoning_effort ?? 'model default'} · {settings.source === 'saved' ? 'saved here' : 'built-in defaults'}.
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
            <div className="field-grid">
              <label className="field"><span>Review mode</span>
                <select className="input" value={form.mode} onChange={e => change({ mode: e.target.value as ReviewMode })}>
                  {(Object.keys(MODE_LABEL) as ReviewMode[]).map(m => <option key={m} value={m}>{MODE_LABEL[m]}</option>)}
                </select>
              </label>
              <ProviderSelect label="Provider" value={form.provider} onChange={p => change({
                provider: p,
                model: p === 'claude' ? settings.claude_model : settings.openai_model,
                reasoning_effort: (p === 'claude' ? settings.claude_reasoning_effort : settings.openai_reasoning_effort) ?? null,
              })} />
              <label className="field"><span>Model ID</span>
                <input className="input" value={form.model} placeholder="A model ID for this provider" required={form.mode !== 'off'} onChange={e => change({ model: e.target.value })} />
              </label>
              <ReasoningEffortField provider={form.provider} value={form.reasoning_effort} onChange={v => change({ reasoning_effort: v })} />
              <label className="field"><span>Reviewer account</span>
                <select className="input" value={form.reviewer_id} required={form.mode !== 'off'} onChange={e => change({ reviewer_id: e.target.value })}>
                  <option value="">Select an active writer or administrator</option>
                  {form.reviewer_id && !reviewerExists && <option value={form.reviewer_id}>Unavailable account ({form.reviewer_id})</option>}
                  {reviewers.map(u => <option key={u.id} value={u.id}>{u.name} ({u.role})</option>)}
                </select>
                <span className="hint">The reviewer acts as a stored, active writer or administrator, also when authentication is off.</span>
              </label>
            </div>
            <p className="hint">{provider?.available ? 'Provider credentials are configured on the server; model access is checked when a review runs.' : provider?.reason || 'This provider has no credentials on the server.'} API credentials are never stored in this form.</p>
            <details className="disclosure">
              <summary>Create a reviewer account</summary>
              <p className="hint">A service account with the writer role for internal reviews. It needs no access token. Save the review settings afterwards to use it.</p>
              <div className="row gap-sm">
                <input className="input grow" aria-label="Reviewer account name" placeholder="Account name" value={accountName} maxLength={80} onChange={e => setAccountName(e.target.value)} />
                <button type="button" className="btn" onClick={() => void createReviewer()} disabled={!accountName.trim()}>Create account</button>
              </div>
            </details>
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
