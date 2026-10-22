// Product settings: per-action limits, concurrency, research repositories and
// documentation delivery. One server document with a section per kind; each
// section saves on its own, guarded by the document revision.
import { useCallback, useState, type FormEvent } from 'react';
import { GitHubConnection, type GitHubRepoConnection } from './github-connection';
import { Card, LoadError, Loading, Notice } from './lib';
import { HttpError, errorMessage, getJSON, patchJSON } from './api';
import { useAsync } from './use-async';

const TITLES: Record<string, string> = {
  ask: 'Questions (Ask)', ingest: 'Ingestion', research: 'Research', docgen: 'Document generation',
  draft_review: 'Draft review', alias_discovery: 'Alias discovery', concurrency: 'Concurrent runs',
  documentation: 'Documentation delivery', sources: 'Research repositories',
};

// [label, min, step]; booleans have no bounds.
const FIELDS: Record<string, [string, number?, (number | 'any')?]> = {
  max_tokens: ['Maximum output tokens', 1, 1], max_retries: ['Request retries', 0, 1],
  request_timeout_s: ['Request timeout (seconds)', 0.1, 'any'], op_cap: ['Maximum tool operations', 1, 1],
  wall_clock_s: ['Run time budget (seconds)', 0.1, 'any'], thinking: ['Claude extended thinking'],
  cache: ['Claude prompt caching'], recon_k: ['Context search results', 1, 1],
  max_input_chars: ['Maximum input characters', 1, 1], max_topic_chars: ['Maximum topic characters', 1, 1],
  max_prompt_chars: ['Maximum prompt characters', 1, 1], model_loops: ['Shared AI runs', 1, 1],
  documentation_runs: ['Document generation runs', 1, 1], research_runs: ['Research runs', 1, 1],
};

export interface Binding { name: string; host: string; available: boolean; label?: string; owner?: string; repo?: string }
interface Destination { name: string; owner: string; repo: string; base_branch: string; path_template: string; binding: string }
interface Source { name: string; owner: string; repo: string; ref: string | null; binding: string | null; host: string }
type Repo = Destination | Source;
type Settings = { kind: string; guideline_set?: string; destinations?: Destination[]; sources?: Source[] } & Record<string, unknown>;
interface Section { settings: Settings; revision: number | string; configuration_error?: string | null }
interface ProductSettingsData { can_configure: boolean; sections: Section[]; github_bindings: Binding[]; guideline_sets: string[]; github_configuration_error?: string | null }

const isDestination = (kind: string) => kind === 'documentation';

function fieldOf(item: Repo, key: string): string {
  for (const [k, v] of Object.entries(item)) if (k === key) return typeof v === 'string' ? v : '';
  return '';
}

function RepositoryFields({ kind, items, bindings, onChange }: { kind: string; items: Repo[]; bindings: Binding[]; onChange: (items: Repo[]) => void }) {
  const destination = isDestination(kind);
  const noun = destination ? 'destination' : 'source';
  const change = (index: number, key: string, value: string | null) => onChange(items.map((item, i) => {
    if (i !== index) return item;
    const next: Repo = { ...item, [key]: value };
    if (key === 'binding' && value) {
      const picked = bindings.find(b => b.name === value);
      if (!destination && 'host' in next) next.host = picked?.host || next.host;
      if (destination && picked?.owner) { next.owner = picked.owner; next.repo = picked.repo || ''; }
    }
    return next;
  }));
  const add = () => onChange([...items, destination
    ? { name: '', owner: bindings[0]?.owner || '', repo: bindings[0]?.repo || '', base_branch: 'main', path_template: 'docs/{slug}.md', binding: bindings[0]?.name || '' }
    : { name: '', owner: '', repo: '', ref: null, binding: null, host: 'github.com' }]);
  const textFields: [string, string][] = destination
    ? [['name', 'Name'], ['owner', 'Repository owner'], ['repo', 'Repository name'], ['base_branch', 'Base branch'], ['path_template', 'File path template']]
    : [['name', 'Name'], ['owner', 'Repository owner'], ['repo', 'Repository name'], ['ref', 'Branch or tag (optional)']];
  return <>
    {items.length === 0 && <p className="muted">No {noun}s configured.</p>}
    {items.map((item, index) => {
      const binding = item.binding ? bindings.find(b => b.name === item.binding) : undefined;
      const appBound = destination && !!item.binding?.startsWith('github-app:');
      return (
        <fieldset key={index} className="subcard">
          <legend>{destination ? 'Destination' : 'Source'} {index + 1}</legend>
          <div className="field-grid">
            {textFields.map(([key, label]) => (
              <label key={key} className="field"><span>{label}</span>
                <input className="input" value={fieldOf(item, key)} readOnly={appBound && (key === 'owner' || key === 'repo')} required={key !== 'ref'}
                  maxLength={key === 'path_template' ? 1000 : 200} onChange={e => change(index, key, key === 'ref' ? e.target.value || null : e.target.value)} />
              </label>
            ))}
            <label className="field"><span>GitHub connection</span>
              <select className="input" value={item.binding || ''} required={destination} onChange={e => change(index, 'binding', e.target.value || null)}>
                <option value="">{destination ? 'Select credentials' : 'Public repository (no credentials)'}</option>
                {item.binding && !binding && <option value={item.binding}>{item.binding} (unavailable)</option>}
                {bindings.map(b => <option key={b.name} value={b.name}>{b.label || b.name} · {b.host}{b.available ? '' : b.name.startsWith('github-app:') ? ' (disconnected)' : ' (credentials unavailable)'}</option>)}
              </select>
            </label>
            {!destination && !item.binding && 'host' in item && (
              <label className="field"><span>GitHub host</span><input className="input" value={item.host} required maxLength={200} onChange={e => change(index, 'host', e.target.value)} /></label>
            )}
          </div>
          {binding && <p className="hint">Host: {binding.host}. {!binding.available && (binding.name.startsWith('github-app:') ? 'Reconnect this repository above before publishing.' : 'The server administrator must configure these credentials before a run can use them.')}</p>}
          {item.binding && !binding && <Notice tone="warn">This credential binding is unavailable. Select a configured one.</Notice>}
          <button type="button" className="btn ghost sm" onClick={() => onChange(items.filter((_, i) => i !== index))}>Remove {noun} {index + 1}</button>
        </fieldset>
      );
    })}
    <button type="button" className="btn sm" onClick={add} disabled={destination && bindings.length === 0}>Add {noun}</button>
    {destination && bindings.length === 0 && <p className="hint">Connect a GitHub repository above to start publishing.</p>}
    <p className="hint">{destination ? 'Use {slug} in the file path template, for example docs/{slug}.md. Publishing opens a pull request for review.' : 'An empty ref uses the repository’s default branch.'} Changes apply to new runs. Repository connections are shared by everyone on this instance.</p>
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
  const bindings: Binding[] = isDestination(kind)
    ? [...data.github_bindings, ...connections.map(c => ({ name: c.name, owner: c.owner, repo: c.repo, label: `${c.owner}/${c.repo}`, host: 'github.com', available: c.enabled }))]
    : data.github_bindings;

  const change = (patch: Partial<Settings>) => { setForm(f => ({ ...f, ...patch })); setSaved(false); };
  const accept = (value: Section) => { setCurrent(value); setForm(value.settings); };
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
            <RepositoryFields kind={kind} items={form.destinations || []} bindings={bindings} onChange={items => change({ destinations: items as Destination[] })} />
          </> : kind === 'sources' ? (
            <RepositoryFields kind={kind} items={form.sources || []} bindings={bindings} onChange={items => change({ sources: items as Source[] })} />
          ) : <>
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
              {['ingest', 'research', 'docgen'].includes(kind) && 'Extended thinking applies when Claude is selected; reasoning effort is set with each action’s model. '}
              {kind === 'concurrency' ? 'Lower limits let running work finish and hold new runs until capacity frees up.' : 'Saved limits apply to new runs.'}
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
  if (state.status === 'loading') return <Loading what="settings" />;
  if (state.status === 'error') return <LoadError error={state.error} what="settings" onRetry={reload} />;
  const data = state.data;
  return <>
    {data.github_configuration_error && <Notice tone="error">{data.github_configuration_error}</Notice>}
    {data.sections.filter(s => kinds.includes(s.settings.kind)).map(s => <ProductSettingsSection key={s.settings.kind} snapshot={s} data={data} onOptions={fresh => update(() => fresh)} />)}
  </>;
}
