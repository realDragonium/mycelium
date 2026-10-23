// Product settings: per-action limits, concurrency and documentation delivery. One server document with a section per kind; each
// section saves on its own, guarded by the document revision.
import { useCallback, useState, type FormEvent } from 'react';
import { GitHubConnection, type GitHubRepoConnection } from './github-connection';
import { Card, LoadError, Loading, Notice } from './lib';
import { HttpError, errorMessage, getJSON, patchJSON } from './api';
import { dataOf, useAsync, useOnSettingsSaved } from './use-async';

const TITLES: Record<string, string> = {
  ask: 'Questions (Ask)', ingest: 'Ingestion', docgen: 'Document generation',
  draft_review: 'Draft review', alias_discovery: 'Alias discovery', concurrency: 'Concurrent runs',
  documentation: 'Documentation delivery', audience_labelling: 'Audience labelling',
  documentation_planning: 'Documentation planning', ai_budget: 'Monthly budget', documentation_maintenance: 'Documentation maintenance', connect: 'Connecting statements',
};

// [label, min, step]; booleans have no bounds.
const FIELDS: Record<string, [string, number?, (number | 'any')?]> = {
  max_tokens: ['Maximum output tokens', 1, 1], max_retries: ['Request retries', 0, 1],
  request_timeout_s: ['Request timeout (seconds)', 0.1, 'any'], op_cap: ['Maximum tool operations', 1, 1],
  wall_clock_s: ['Run time budget (seconds)', 0.1, 'any'], thinking: ['Claude extended thinking'],
  cache: ['Claude prompt caching'], recon_k: ['Context search results', 1, 1],
  max_input_chars: ['Maximum input characters', 1, 1],
  max_prompt_chars: ['Maximum prompt characters', 1, 1], model_loops: ['Shared AI runs', 1, 1],
  documentation_runs: ['Document generation runs', 1, 1],
  automatic: ['Automatic labelling'], batch_size: ['Batch size', 1, 1],
  max_entities: ['Concepts in the overview', 1, 1], max_capabilities: ['Key statements in the overview', 0, 1],
  max_items: ['Maximum proposed documents', 1, 1], coverage_min_statements: ['Coverage gap from statements', 1, 1],
  replan_hint_statements: ['Re-plan hint after new statements', 1, 1], approve_batch: ['Items per batch approval', 1, 1],
  monthly_limit_usd: ['Monthly budget in USD (0 for none)', 0, 'any'], warn_percent: ['Warn admins at percent of budget', 1, 1],
  pause_background: ['Pause background actions at 100%'],
  quiet_minutes: ['Quiet minutes before an automatic revision', 0, 1], revisions_per_day: ['Automatic revisions per profile per day', 0, 1],
  max_cost_usd: ['Spending cap per run (USD)', 0.01, 'any'],
};

export interface Binding { name: string; host: string; available: boolean; label?: string; owner?: string; repo?: string }
interface Destination { name: string; owner: string; repo: string; base_branch: string; path_template: string; binding: string }
type Settings = { kind: string; guideline_set?: string; destinations?: Destination[] } & Record<string, unknown>;
interface Section { settings: Settings; revision: number | string; configuration_error?: string | null }
interface ProductSettingsData { can_configure: boolean; sections: Section[]; github_bindings: Binding[]; guideline_sets: string[]; github_configuration_error?: string | null }

const isDestination = (kind: string) => kind === 'documentation';

const TEXT_FIELDS: [keyof Destination, string][] = [
  ['name', 'Name'], ['owner', 'Repository owner'], ['repo', 'Repository name'], ['base_branch', 'Base branch'], ['path_template', 'File path template'],
];

function DestinationFields({ items, bindings, onChange }: { items: Destination[]; bindings: Binding[]; onChange: (items: Destination[]) => void }) {
  const change = (index: number, key: keyof Destination, value: string) => onChange(items.map((item, i) => {
    if (i !== index) return item;
    const next: Destination = { ...item, [key]: value };
    if (key === 'binding' && value) {
      const picked = bindings.find(b => b.name === value);
      if (picked?.owner) { next.owner = picked.owner; next.repo = picked.repo || ''; }
    }
    return next;
  }));
  const add = () => onChange([...items, { name: '', owner: bindings[0]?.owner || '', repo: bindings[0]?.repo || '', base_branch: 'main', path_template: 'docs/{slug}.md', binding: bindings[0]?.name || '' }]);
  return <>
    {items.length === 0 && <p className="muted">No destinations configured.</p>}
    {items.map((item, index) => {
      const binding = item.binding ? bindings.find(b => b.name === item.binding) : undefined;
      const appBound = !!item.binding?.startsWith('github-app:');
      return (
        <fieldset key={index} className="subcard">
          <legend>Destination {index + 1}</legend>
          <div className="field-grid">
            {TEXT_FIELDS.map(([key, label]) => (
              <label key={key} className="field"><span>{label}</span>
                <input className="input" value={item[key]} readOnly={appBound && (key === 'owner' || key === 'repo')} required
                  maxLength={key === 'path_template' ? 1000 : 200} onChange={e => change(index, key, e.target.value)} />
              </label>
            ))}
            <label className="field"><span>GitHub connection</span>
              <select className="input" value={item.binding || ''} required onChange={e => change(index, 'binding', e.target.value)}>
                <option value="">Select credentials</option>
                {item.binding && !binding && <option value={item.binding}>{item.binding} (unavailable)</option>}
                {bindings.map(b => <option key={b.name} value={b.name}>{b.label || b.name} · {b.host}{b.available ? '' : b.name.startsWith('github-app:') ? ' (disconnected)' : ' (credentials unavailable)'}</option>)}
              </select>
            </label>
          </div>
          {binding && <p className="hint">Host: {binding.host}. {!binding.available && (binding.name.startsWith('github-app:')
            ? 'Reconnect this repository above before publishing.'
            : 'The server administrator must configure these credentials before a run can use them.')}</p>}
          {item.binding && !binding && <Notice tone="warn">This credential binding is unavailable. Select a configured one.</Notice>}
          <button type="button" className="btn ghost sm" onClick={() => onChange(items.filter((_, i) => i !== index))}>Remove destination {index + 1}</button>
        </fieldset>
      );
    })}
    <button type="button" className="btn sm" onClick={add} disabled={bindings.length === 0}>Add destination</button>
    {bindings.length === 0 && <p className="hint">Connect a GitHub repository above to start publishing.</p>}
    <p className="hint">Use {'{slug}'} in the file path template, for example docs/{'{slug}'}.md. Publishing opens a pull request for review. Changes apply to new runs. Repository connections are shared by everyone on this instance.</p>
  </>;
}

function ProductSettingsSection({ snapshot, data, onOptions }: { snapshot: Section; data: ProductSettingsData; onOptions: (d: ProductSettingsData) => void }) {
  const [current, setCurrent] = useState(snapshot);
  const [form, setForm] = useState(snapshot.settings);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [connections, setConnections] = useState<GitHubRepoConnection[]>([]);
  const kind = snapshot.settings.kind;
  const title = TITLES[kind] || kind;
  const canConfigure = data.can_configure;
  const bindings: Binding[] = [
    ...data.github_bindings,
    ...connections.map(c => ({ name: c.name, owner: c.owner, repo: c.repo, label: `${c.owner}/${c.repo}`, host: 'github.com', available: c.enabled })),
  ];
  // Destinations get their connections from the GitHubConnection panel.

  const change = (patch: Partial<Settings>) => { setForm(f => ({ ...f, ...patch })); setSaved(false); };
  const accept = (value: Section) => { setCurrent(value); setForm(value.settings); };
  // A save elsewhere reloads the document; take this section unless it has edits.
  const [seen, setSeen] = useState(snapshot);
  if (snapshot !== seen) {
    setSeen(snapshot);
    if (snapshot.revision !== current.revision && JSON.stringify(form) === JSON.stringify(current.settings)) accept(snapshot);
  }
  // A newly connected repository becomes a destination, named after the repo.
  const connected = (c: GitHubRepoConnection) => {
    setConnections(prev => [...prev.filter(x => x.name !== c.name), { ...c, enabled: true }]);
    setForm(prev => {
      const destinations = prev.destinations || [];
      if (destinations.some(d => d.binding === c.name)) return prev;
      const names = new Set(destinations.map(d => d.name));
      let name = c.repo, n = 2;
      while (names.has(name)) name = `${c.repo}-${n++}`;
      return { ...prev, destinations: [...destinations, { name, owner: c.owner, repo: c.repo, base_branch: c.base_branch || 'main', path_template: 'docs/{slug}.md', binding: c.name }] };
    });
    setSaved(false);
  };
  const reload = async () => {
    setBusy(true); setError(null); setSaved(false);
    try {
      const fresh = await getJSON<ProductSettingsData>('/api/product-settings');
      const section = fresh.sections.find(s => s.settings.kind === kind);
      if (!section) throw new Error('These settings are unavailable.');
      accept(section); onOptions(fresh); setConflict(false);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };
  const save = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError(null); setSaved(false);
    try {
      accept(await patchJSON<Section>('/api/product-settings', { revision: current.revision, settings: form })); setSaved(true);
    } catch (ex) {
      if (ex instanceof HttpError && ex.status === 409) { setConflict(true); setError('Someone else changed these settings. Reload before saving again.'); }
      else setError(errorMessage(ex, 'Settings could not be saved. Check the values.'));
    } finally { setBusy(false); }
  };

  const numericKeys = Object.keys(form).filter(k => k !== 'kind' && FIELDS[k]);
  return (
    <Card title={<>{title}{current.configuration_error && <span className="warn-text small"> · needs attention</span>}</>}
      actions={<button type="button" className="btn ghost sm" onClick={() => void reload()} disabled={busy}>Reload</button>}>
      {current.configuration_error && <Notice tone="error">{current.configuration_error}</Notice>}
      {error && <Notice tone="error">{error}</Notice>}
      {isDestination(kind) && <GitHubConnection canConfigure={canConfigure} onConnected={connected} onConnections={setConnections} />}
      <form onSubmit={save}>
        <fieldset disabled={busy || conflict || !canConfigure}>
          {isDestination(kind) ? <>
            <label className="field"><span>Default writing profile</span>
              <select className="input" value={form.guideline_set || ''} required onChange={e => change({ guideline_set: e.target.value })}>
                <option value="">Select a profile</option>
                {form.guideline_set && !data.guideline_sets.includes(form.guideline_set) && <option value={form.guideline_set}>{form.guideline_set} (unavailable)</option>}
                {data.guideline_sets.map(n => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <DestinationFields items={form.destinations || []} bindings={bindings} onChange={items => change({ destinations: items })} />
          </> : <>
            <div className="field-grid">
              {numericKeys.map(key => {
                const [label, min, step] = FIELDS[key];
                const value = form[key];
                return typeof value === 'boolean'
                  ? <label key={key} className="check"><input type="checkbox" checked={value} onChange={e => change({ [key]: e.target.checked })} />{label}</label>
                  : <label key={key} className="field"><span>{label}</span><input className="input" type="number" value={typeof value === 'number' ? value : ''} min={min} step={step} required
                      onChange={e => change({ [key]: e.target.value === '' ? '' : Number(e.target.value) })} /></label>;
              })}
            </div>
            <p className="hint">
              {kind === 'ask' && 'Quick questions keep their smaller built-in limits. Thinking and caching apply when Claude is selected. '}
              {['ingest', 'docgen'].includes(kind) && 'Extended thinking applies when Claude is selected; reasoning effort is set with each action’s model. '}
              {kind === 'concurrency' ? 'Lower limits let running work finish and hold new runs until capacity frees up.'
                : kind === 'ai_budget' ? 'A soft limit on estimated spend per UTC calendar month. Admins see a banner once spend passes the warning percentage. With pausing on, reaching 100% stops audience labelling, draft review and the connect pass from calling a model until the month ends or the budget is raised; Ask, ingest, documentation and alias discovery always run.'
                : 'Saved limits apply to new runs.'}
            </p>
          </>}
          {canConfigure && <div className="row gap-sm"><button type="submit" className="btn primary">{busy ? 'Saving…' : 'Save'}</button>{saved && <span className="ok-text small" role="status">Saved.</span>}</div>}
        </fieldset>
      </form>
      {!canConfigure && <p className="hint">Only administrators can change these settings.</p>}
    </Card>
  );
}

export function ProductSettings({ kinds }: { kinds: string[] }) {
  const { state, reload, update } = useAsync(useCallback(() => getJSON<ProductSettingsData>('/api/product-settings'), []));
  useOnSettingsSaved(reload);
  const data = dataOf(state);
  if (!data) return state.status === 'error' ? <LoadError error={state.error} what="settings" onRetry={reload} /> : <Loading what="settings" />;
  return <>
    {data.github_configuration_error && <Notice tone="error">{data.github_configuration_error}</Notice>}
    {data.sections.filter(s => kinds.includes(s.settings.kind)).map(s => <ProductSettingsSection key={s.settings.kind} snapshot={s} data={data} onOptions={fresh => update(() => fresh)} />)}
  </>;
}
