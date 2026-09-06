const productSettingsTitles = {
  ask: 'Question limits', ingest: 'Ingestion limits', research: 'Research limits',
  docgen: 'Document generation limits', draft_review: 'Draft review limits',
  concurrency: 'Concurrent runs', documentation: 'Documentation delivery', sources: 'Research repositories',
};

const productSettingsFields = {
  max_tokens: ['Maximum output tokens', 1, 1], max_retries: ['Request retries', 0, 1],
  request_timeout_s: ['Request timeout (seconds)', 0.1, 'any'], op_cap: ['Maximum tool operations', 1, 1],
  wall_clock_s: ['Run time budget (seconds)', 0.1, 'any'], thinking: ['Claude extended thinking'],
  cache: ['Claude prompt caching'], recon_k: ['Context search results', 1, 1],
  max_input_chars: ['Maximum input characters', 1, 1], max_topic_chars: ['Maximum topic characters', 1, 1],
  max_prompt_chars: ['Maximum prompt characters', 1, 1], model_loops: ['Shared AI runs', 1, 1],
  documentation_runs: ['Document generation runs', 1, 1], research_runs: ['Research runs', 1, 1],
};

const productSettingsStyle = {
  input: { minWidth: 0, width: '100%', boxSizing: 'border-box', padding: '8px 10px', border: '1px solid var(--rule, var(--line))', borderRadius: 4, color: 'var(--ink)', background: 'var(--surface-2, var(--paper))' },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 14 },
  field: { display: 'grid', gap: 6, minWidth: 0 },
  button: { padding: '8px 14px', border: '1px solid var(--rule, var(--line))', borderRadius: 4, color: 'var(--ink)', background: 'var(--surface-2, var(--paper))' },
};

function RepositorySettingsFields({ kind, items, bindings, onChange }) {
  const destination = kind === 'documentation';
  const noun = destination ? 'destination' : 'source';
  const change = (index, key, value) => onChange(items.map((item, i) => {
    if (i !== index) return item;
    const next = { ...item, [key]: value };
    if (key === 'binding' && !destination && value) next.host = bindings.find(binding => binding.name === value)?.host || item.host;
    return next;
  }));
  const add = () => onChange([...items, destination
    ? { name: '', owner: '', repo: '', base_branch: 'main', path_template: 'docs/{slug}.md', binding: bindings[0]?.name || '' }
    : { name: '', owner: '', repo: '', ref: null, binding: null, host: 'github.com' }]);
  return <>
    {items.length === 0 && <p>No {destination ? 'destinations' : 'sources'} configured.</p>}
    {items.map((item, index) => {
      const selectedBinding = bindings.find(binding => binding.name === item.binding);
      const textFields = destination
        ? [['name', 'Name'], ['owner', 'Repository owner'], ['repo', 'Repository name'], ['base_branch', 'Base branch'], ['path_template', 'File path template']]
        : [['name', 'Name'], ['owner', 'Repository owner'], ['repo', 'Repository name'], ['ref', 'Branch or tag (optional)']];
      return <fieldset key={index} style={{ padding: 14, margin: '12px 0', minWidth: 0, border: '1px solid var(--rule, var(--line))', borderRadius: 4 }}>
        <legend>{destination ? 'Destination' : 'Source'} {index + 1}</legend>
        <div style={productSettingsStyle.grid}>
          {textFields.map(([key, label]) => <label key={key} style={productSettingsStyle.field}>{label}
            <input aria-label={`${noun} ${index + 1} ${label}`} style={productSettingsStyle.input} value={item[key] ?? ''} required={key !== 'ref'} maxLength={key === 'path_template' ? 1000 : 200} onChange={event => change(index, key, key === 'ref' ? event.target.value || null : event.target.value)} />
          </label>)}
          <label style={productSettingsStyle.field}>GitHub credentials
            <select aria-label={`${noun} ${index + 1} GitHub credentials`} style={productSettingsStyle.input} value={item.binding || ''} required={destination} onChange={event => change(index, 'binding', event.target.value || null)}>
              <option value="">{destination ? 'Select credentials' : 'Public repository (no credentials)'}</option>
              {item.binding && !selectedBinding && <option value={item.binding}>{item.binding} (unavailable)</option>}
              {bindings.map(binding => <option key={binding.name} value={binding.name}>{binding.name} · {binding.host}{binding.available ? '' : ' (credentials unavailable)'}</option>)}
            </select>
          </label>
          {!destination && !item.binding && <label style={productSettingsStyle.field}>GitHub host
            <input aria-label={`${noun} ${index + 1} GitHub host`} style={productSettingsStyle.input} value={item.host} required maxLength={200} onChange={event => change(index, 'host', event.target.value)} />
          </label>}
        </div>
        {selectedBinding && <p>Host: {selectedBinding.host}. {!selectedBinding.available && 'The server administrator must configure these credentials before a run can use them.'}</p>}
        {item.binding && !selectedBinding && <p role="alert">This credential binding is unavailable. Select a configured binding.</p>}
        <button type="button" style={productSettingsStyle.button} onClick={() => onChange(items.filter((_, i) => i !== index))}>Remove {noun} {index + 1}</button>
      </fieldset>;
    })}
    <button type="button" style={productSettingsStyle.button} onClick={add} disabled={destination && bindings.length === 0}>Add {noun}</button>
    {destination && bindings.length === 0 && <p>A server administrator must configure GitHub credentials before you can add a destination.</p>}
    <p>{destination ? 'Use {slug} in the file path template, for example docs/{slug}.md. Delivery creates a pull request for review.' : 'An empty ref uses the repository’s default branch.'} Repository changes take effect for new runs.</p>
    <p>Credential bindings and tokens are managed on the server. This form stores the selected binding name.</p>
  </>;
}

function ProductSettingsSection({ snapshot, canConfigure, bindings, guidelineSets, onOptions }) {
  const [current, setCurrent] = React.useState(snapshot);
  const [form, setForm] = React.useState(snapshot.settings);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [saved, setSaved] = React.useState(false);
  const [conflict, setConflict] = React.useState(false);
  const kind = snapshot.settings.kind;
  const title = productSettingsTitles[kind];
  const change = (key, value) => { setForm(previous => ({ ...previous, [key]: value })); setSaved(false); };
  const accept = value => { setCurrent(value); setForm(value.settings); };
  const reload = async () => {
    setBusy(true); setError(null); setSaved(false);
    try {
      const response = await fetch('/api/product-settings');
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Settings could not be loaded.');
      const section = data.sections.find(item => item.settings.kind === kind);
      if (!section) throw new Error('These settings are unavailable.');
      accept(section); onOptions(data); setConflict(false);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const save = async event => {
    event.preventDefault(); setBusy(true); setError(null); setSaved(false);
    try {
      const response = await fetch('/api/product-settings', {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ revision: current.revision, settings: form }),
      });
      const data = await response.json();
      if (response.status === 409) {
        setConflict(true);
        throw new Error('Another administrator changed these settings. Reload before saving again.');
      }
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Settings could not be saved. Check the field values.');
      accept(data); setSaved(true);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  return <details style={{ border: '1px solid var(--rule, var(--line))', borderRadius: 6, padding: '16px 20px', marginBottom: 12, minWidth: 0, overflowWrap: 'anywhere' }}>
    <summary style={{ cursor: 'pointer', color: 'var(--ink)', fontWeight: 600 }}>{title}{current.configuration_error ? ' · Needs attention' : ''}</summary>
    {current.configuration_error && <p role="alert" style={{ color: 'var(--red, #dc2626)' }}>{current.configuration_error}</p>}
    {error && <p role="alert" style={{ color: 'var(--red, #dc2626)' }}>{error}</p>}
    <form onSubmit={save}>
      <fieldset disabled={busy || conflict || !canConfigure} style={{ border: 0, padding: 0, margin: '16px 0 0', minWidth: 0 }}>
        {kind === 'documentation' ? <>
          <label style={productSettingsStyle.field}>Default guideline set
            <select style={productSettingsStyle.input} value={form.guideline_set} required onChange={event => change('guideline_set', event.target.value)}>
              <option value="">Select a guideline set</option>
              {form.guideline_set && !guidelineSets.includes(form.guideline_set) && <option value={form.guideline_set}>{form.guideline_set} (unavailable)</option>}
              {guidelineSets.map(name => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
          <RepositorySettingsFields kind={kind} items={form.destinations} bindings={bindings} onChange={items => change('destinations', items)} />
        </> : kind === 'sources' ? <RepositorySettingsFields kind={kind} items={form.sources} bindings={bindings} onChange={items => change('sources', items)} /> : <>
          <div style={productSettingsStyle.grid}>
            {Object.keys(form).filter(key => key !== 'kind' && productSettingsFields[key]).map(key => {
              const [label, min, step] = productSettingsFields[key];
              return typeof form[key] === 'boolean'
                ? <label key={key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}><input type="checkbox" checked={form[key]} onChange={event => change(key, event.target.checked)} />{label}</label>
                : <label key={key} style={productSettingsStyle.field}>{label}<input style={productSettingsStyle.input} type="number" value={form[key]} min={min} step={step} required onChange={event => change(key, event.target.value === '' ? '' : Number(event.target.value))} /></label>;
            })}
          </div>
          {kind === 'ask' && <p>Quick questions keep their smaller built-in limits. Claude thinking and caching options apply when Claude is selected.</p>}
          {['ingest', 'research', 'docgen'].includes(kind) && <p>Extended thinking applies when Claude is selected.</p>}
          {kind === 'concurrency' ? <p>Lower limits let active work finish and restrict new runs until capacity is available.</p> : <p>Saved limits apply to new runs.</p>}
        </>}
        {canConfigure && <button type="submit" style={{ ...productSettingsStyle.button, marginTop: 12, fontWeight: 600 }}>{busy ? 'Saving…' : `Save ${title.toLowerCase()}`}</button>}
      </fieldset>
    </form>
    {!canConfigure && <p>Only administrators can change these settings.</p>}
    {saved && <p role="status">{title} saved.</p>}
    <button type="button" style={{ ...productSettingsStyle.button, marginTop: 12 }} onClick={reload} disabled={busy}>Reload {title.toLowerCase()}</button>
  </details>;
}

function ProductSettings() {
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [retry, setRetry] = React.useState(0);
  React.useEffect(() => {
    let cancelled = false;
    setError(null);
    fetch('/api/product-settings').then(async response => {
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'Product settings could not be loaded.');
      if (!cancelled) setData(value);
    }).catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [retry]);
  return <section aria-label="AI limits and repositories" style={{ color: 'var(--ink-3)', fontSize: 13, lineHeight: 1.5 }}>
    <h2 style={{ color: 'var(--ink)', fontSize: 18 }}>AI limits and repositories</h2>
    <p>Configure each action’s limits, research repositories, and documentation delivery separately.</p>
    {data?.github_configuration_error && <p role="alert" style={{ color: 'var(--red, #dc2626)' }}>{data.github_configuration_error}</p>}
    {error ? <><p role="alert" style={{ color: 'var(--red, #dc2626)' }}>{error}</p><button onClick={() => setRetry(value => value + 1)} style={productSettingsStyle.button}>Reload product settings</button></>
      : !data ? <p>Loading product settings…</p>
      : data.sections.map(snapshot => <ProductSettingsSection key={snapshot.settings.kind} snapshot={snapshot} canConfigure={data.can_configure} bindings={data.github_bindings} guidelineSets={data.guideline_sets} onOptions={setData} />)}
  </section>;
}

Object.assign(window, { ProductSettings });
