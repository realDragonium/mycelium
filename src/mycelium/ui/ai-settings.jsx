function ReasoningEffortField({ provider, value, onChange, label = 'Reasoning effort', style }) {
  const levels = provider === 'claude' ? ['low', 'medium', 'high', 'xhigh', 'max'] : ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'];
  return <label style={{ display: 'grid', gap: 6, minWidth: 0 }}>{label}
    <select aria-label={label} style={style} value={value ?? ''} onChange={event => onChange(event.target.value || null)}>
      <option value="">Model default</option>
      {levels.map(level => <option key={level} value={level}>{level === 'xhigh' ? 'Extra high' : level[0].toUpperCase() + level.slice(1)}</option>)}
    </select>
    <span>Supported levels depend on the model. Higher effort can use more tokens and time; existing limits still apply.</span>
  </label>;
}

function draftReviewProviderName(provider) {
  return provider === 'claude' ? 'Claude' : provider === 'openai' ? 'GPT (OpenAI)' : 'Unknown provider';
}

function DraftReviewSettings() {
  const [settings, setSettings] = React.useState(null);
  const [form, setForm] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [saved, setSaved] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [conflict, setConflict] = React.useState(false);
  const [accountName, setAccountName] = React.useState('');

  const accept = data => {
    setSettings(data);
    setForm({ application_enabled: data.application_enabled, mode: data.mode, provider: data.provider, model: data.model, reasoning_effort: data[data.provider === 'claude' ? 'claude_reasoning_effort' : 'openai_reasoning_effort'] ?? null, reviewer_id: data.reviewer_id, revision: data.revision, model_revision: data.model_revision });
  };
  const reload = React.useCallback(async () => {
    setBusy(true); setError(null); setSaved(false);
    try {
      const response = await fetch('/api/draft-review/settings');
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Review settings could not be loaded.');
      accept(data); setConflict(false);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }, []);
  React.useEffect(() => { reload(); }, [reload]);

  const change = (key, value) => {
    setForm(current => ({ ...current, [key]: value }));
    setSaved(false);
  };
  const save = async event => {
    event.preventDefault();
    setBusy(true); setError(null); setSaved(false);
    try {
      const response = await fetch('/api/draft-review/settings', {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ...form, model: form.model.trim() }),
      });
      const data = await response.json();
      if (response.status === 409) {
        setConflict(true);
        throw new Error('Another administrator changed these settings. Reload the current settings before saving again.');
      }
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Review settings could not be saved.');
      accept(data); setSaved(true);
      window.dispatchEvent(new Event('draft-review-settings-changed'));
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const createReviewer = async () => {
    setBusy(true); setError(null); setSaved(false);
    try {
      const response = await fetch('/api/admin/users', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name: accountName.trim(), role: 'writer', type: 'service' }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Reviewer account could not be created.');
      setSettings(current => ({ ...current, reviewers: [...current.reviewers, data.user] }));
      setForm(current => ({ ...current, reviewer_id: data.user.id }));
      setAccountName('');
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const selectedProvider = settings?.providers.find(item => item.provider === form?.provider);
  const reviewerExists = settings?.reviewers.some(item => item.id === form?.reviewer_id);
  const incomplete = form?.mode !== 'off' && (!form?.model.trim() || !reviewerExists || !selectedProvider?.available);
  const buttonStyle = { padding: '8px 14px', border: '1px solid var(--rule, var(--line))', borderRadius: 4, color: 'var(--ink)', background: 'var(--surface-2, var(--paper))' };
  const fieldStyle = { display: 'grid', gap: 6, minWidth: 0 };
  const inputStyle = { width: '100%', minWidth: 0, boxSizing: 'border-box', padding: '8px 10px', fontSize: 13, color: 'var(--ink)', background: 'var(--surface-2, var(--paper))', border: '1px solid var(--rule, var(--line))', borderRadius: 4 };
  const body = <div style={{ marginTop: 14 }}>
    {error && <p role="alert" style={{ color: 'var(--red, #dc2626)' }}>{error}</p>}
    {!settings && !error && <p>Loading review settings…</p>}
    {settings && <>
      <p style={{ marginTop: 0 }}>
        Current: {settings.mode === 'off' ? 'Off' : settings.mode === 'review-only' ? 'Review only' : 'Review and apply'}
        {' · '}{draftReviewProviderName(settings.provider)}{settings.model ? ` · ${settings.model}` : ' · No model configured'}.
        {' · Effort: '}{settings.reasoning_effort ?? 'Model default'}.
        {' '}{settings.source === 'saved' ? 'Saved in Mycelium.' : 'Using built-in defaults.'}
      </p>
      {settings.issues.length > 0 && <ul style={{ paddingLeft: 20 }}>{settings.issues.map(issue => <li key={issue}>{issue}</li>)}</ul>}
      <p>Applying accepted reviews is {settings.application_enabled ? 'enabled' : 'disabled'}. This permission covers manual curator application and automatic application.</p>
      {settings.can_configure ? <form onSubmit={save}>
        <fieldset disabled={busy || conflict} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
          <label style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
            <input type="checkbox" checked={form.application_enabled} onChange={event => change('application_enabled', event.target.checked)} />
            Allow applying accepted reviews
          </label>
          <p>Automatic application also requires Review and apply mode. This permission can be enabled while automatic reviews are Off.</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 14 }}>
            <label style={fieldStyle}>Review mode
              <select aria-label="Review mode" style={inputStyle} value={form.mode} onChange={event => change('mode', event.target.value)}>
                <option value="off">Off</option><option value="review-only">Review only</option><option value="review-and-apply">Review and apply</option>
              </select>
            </label>
            <label style={fieldStyle}>Provider
              <select aria-label="Provider" style={inputStyle} value={form.provider} onChange={event => { setForm(current => ({ ...current, provider: event.target.value, model: settings[event.target.value === 'claude' ? 'claude_model' : 'openai_model'], reasoning_effort: settings[event.target.value === 'claude' ? 'claude_reasoning_effort' : 'openai_reasoning_effort'] ?? null })); setSaved(false); }}>
                <option value="claude">Claude (Anthropic)</option><option value="openai">GPT (OpenAI)</option>
              </select>
            </label>
            <label style={fieldStyle}>Model ID
              <input style={inputStyle} value={form.model} onChange={event => change('model', event.target.value)} placeholder="Enter a model ID for this provider" required={form.mode !== 'off'} />
            </label>
            <ReasoningEffortField provider={form.provider} value={form.reasoning_effort} onChange={value => change('reasoning_effort', value)} label="Draft review reasoning effort" style={inputStyle} />
            <label style={fieldStyle}>Reviewer account
              <select aria-label="Reviewer account" style={inputStyle} value={form.reviewer_id} onChange={event => change('reviewer_id', event.target.value)} required={form.mode !== 'off'}>
                <option value="">Select an active writer or administrator</option>
                {form.reviewer_id && !reviewerExists && <option value={form.reviewer_id}>Unavailable account ({form.reviewer_id})</option>}
                {settings.reviewers.map(user => <option key={user.id} value={user.id}>{user.name} ({user.role})</option>)}
              </select>
            </label>
          </div>
          <p>{selectedProvider?.available ? 'Provider credentials are configured on the server. Model access is checked when a review runs.' : selectedProvider?.reason || 'This provider has no server credentials configured.'} API credentials are never stored in this form.</p>
          <p>The reviewer must be a stored, active writer or administrator, including when authentication is disabled.</p>
          <details style={{ marginBottom: 16 }}><summary style={{ cursor: 'pointer' }}>Create a reviewer account</summary>
            <p>Create a service account with writer permissions for internal reviews. No access token is needed.</p>
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'end', gap: 8 }}>
              <label style={{ ...fieldStyle, flex: '1 1 200px' }}>Account name
                <input style={inputStyle} value={accountName} maxLength={80} onChange={event => setAccountName(event.target.value)} />
              </label>
              <button type="button" onClick={createReviewer} disabled={!accountName.trim()} style={buttonStyle}>Create account</button>
            </div>
            <p>The account is created immediately. Save review settings to use it.</p>
          </details>
          <p>Saving changes affects new submissions and reruns. Reviews already running can finish, but cannot apply automatically after the settings change. Run them again to use the new settings.</p>
          {incomplete && <p>Choose a model, a reviewer account, and a provider with server credentials before enabling reviews. You can always save Off.</p>}
          <button type="submit" disabled={incomplete} style={{ ...buttonStyle, fontWeight: 600, opacity: incomplete ? 0.5 : 1 }}>{busy ? 'Saving…' : 'Save review settings'}</button>
        </fieldset>
      </form> : <p>Only administrators can change these settings. Writers can still run or rerun draft reviews.</p>}
      {saved && <p role="status">Review settings saved.</p>}
    </>}
    <button type="button" onClick={reload} disabled={busy} style={{ ...buttonStyle, marginTop: 12 }}>Reload current settings</button>
  </div>;
  const style = { padding: '18px 20px', marginBottom: 24, border: '1px solid var(--rule, var(--line))', borderRadius: 6, fontSize: 13, lineHeight: 1.5, color: 'var(--ink-3)', overflowWrap: 'anywhere' };
  return <section aria-label="Draft review settings" style={style}><h2 style={{ margin: 0, color: 'var(--ink)', fontSize: 16 }}>Draft review settings</h2>{body}</section>;
}

function ActionModelSettings({ settings, canConfigure }) {
  const [current, setCurrent] = React.useState(settings);
  const [form, setForm] = React.useState({ provider: settings.provider, claude_model: settings.claude_model, openai_model: settings.openai_model, claude_reasoning_effort: settings.claude_reasoning_effort ?? null, openai_reasoning_effort: settings.openai_reasoning_effort ?? null, revision: settings.revision });
  const [error, setError] = React.useState(null);
  const [saved, setSaved] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [conflict, setConflict] = React.useState(false);
  const titles = { ask: 'Questions', ingest: 'Ingestion', research: 'Research', docgen: 'Document generation', alias_discovery: 'Alias discovery' };
  const title = titles[settings.action];
  const effortKey = form.provider === 'claude' ? 'claude_reasoning_effort' : 'openai_reasoning_effort';
  const modelKey = form.provider === 'claude' ? 'claude_model' : 'openai_model';
  const selectedProvider = current.providers.find(item => item.provider === form.provider);
  const accept = value => {
    setCurrent(value);
    setForm({ provider: value.provider, claude_model: value.claude_model, openai_model: value.openai_model, claude_reasoning_effort: value.claude_reasoning_effort ?? null, openai_reasoning_effort: value.openai_reasoning_effort ?? null, revision: value.revision });
  };
  const reload = async () => {
    setBusy(true); setError(null); setSaved(false);
    try {
      const response = await fetch('/api/model-settings');
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'AI settings could not be loaded.');
      const value = data.actions.find(item => item.action === settings.action);
      if (!value) throw new Error('These model settings are unavailable.');
      accept(value); setConflict(false);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const save = async event => {
    event.preventDefault(); setBusy(true); setError(null); setSaved(false);
    try {
      const response = await fetch(`/api/model-settings/${settings.action}`, {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ...form, claude_model: form.claude_model.trim(), openai_model: form.openai_model.trim() }),
      });
      const data = await response.json();
      if (response.status === 409) {
        setConflict(true);
        throw new Error('Another administrator changed this action. Reload its current settings before saving again.');
      }
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Model settings could not be saved.');
      accept(data); setSaved(true);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const fieldStyle = { display: 'grid', gap: 6, minWidth: 0 };
  const inputStyle = { minWidth: 0, width: '100%', boxSizing: 'border-box', padding: '8px 10px', border: '1px solid var(--rule, var(--line))', borderRadius: 4, color: 'var(--ink)', background: 'var(--surface-2, var(--paper))' };
  const buttonStyle = { padding: '8px 14px', border: '1px solid var(--rule, var(--line))', borderRadius: 4, color: 'var(--ink)' };
  return <section aria-label={`${title} model settings`} style={{ padding: '18px 20px', marginBottom: 16, border: '1px solid var(--rule, var(--line))', borderRadius: 6, color: 'var(--ink-3)', fontSize: 13, lineHeight: 1.5, overflowWrap: 'anywhere' }}>
    <h2 style={{ margin: 0, fontSize: 16, color: 'var(--ink)' }}>{title}</h2>
    <p>Current: {draftReviewProviderName(current.provider)} · {current.model || 'No model configured'}.
      {' · Effort: '}{current[current.provider === 'claude' ? 'claude_reasoning_effort' : 'openai_reasoning_effort'] ?? 'Model default'}.
      {' '}{current.source === 'saved' ? 'Saved in Mycelium.' : 'Using built-in defaults.'}
    </p>
    {settings.action === 'docgen' && <p>These are the model and effort defaults for new documents. Choosing a different provider in the generation screen uses its saved model and effort.</p>}
    {current.configuration_error && <p role="alert" style={{ color: 'var(--red, #dc2626)' }}>{current.configuration_error} Save valid settings to enable this action.</p>}
    {error && <p role="alert" style={{ color: 'var(--red, #dc2626)' }}>{error}</p>}
    {canConfigure ? <>
      <form onSubmit={save}><fieldset disabled={busy || conflict} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 14 }}>
          <label style={fieldStyle}>Provider<select aria-label={`${title} provider`} style={inputStyle} value={form.provider} onChange={event => { setForm(value => ({ ...value, provider: event.target.value })); setSaved(false); }}><option value="claude">Claude (Anthropic)</option><option value="openai">GPT (OpenAI)</option></select></label>
          <label style={fieldStyle}>Model ID<input aria-label={`${title} model ID`} style={inputStyle} value={form[modelKey]} onChange={event => { setForm(value => ({ ...value, [modelKey]: event.target.value })); setSaved(false); }} placeholder="Enter a model ID for this provider" required /></label>
          <ReasoningEffortField provider={form.provider} value={form[effortKey]} onChange={value => { setForm(current => ({ ...current, [effortKey]: value })); setSaved(false); }} label={`${title} reasoning effort`} style={inputStyle} />
        </div>
        <p>{selectedProvider?.available ? 'Provider credentials are configured on the server.' : selectedProvider?.reason || 'Provider credentials are unavailable.'}</p>
        <button type="submit" disabled={!form[modelKey].trim()} style={{ ...buttonStyle, fontWeight: 600 }}>{busy ? 'Saving…' : `Save ${title.toLowerCase()} settings`}</button>
      </fieldset></form>
      {saved && <p role="status">{title} settings saved.</p>}
      <button type="button" onClick={reload} disabled={busy} style={{ ...buttonStyle, marginTop: 10 }}>Reload {title.toLowerCase()} settings</button>
    </> : <p>Only administrators can change this model.</p>}
  </section>;
}

function AISettings() {
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [retry, setRetry] = React.useState(0);
  React.useEffect(() => {
    let cancelled = false;
    setError(null);
    fetch('/api/model-settings').then(async response => {
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'AI settings could not be loaded.');
      if (!cancelled) setData(value);
    }).catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [retry]);
  return <div>
    <p style={{ color: 'var(--ink-3)', fontSize: 13, lineHeight: 1.5 }}>Choose the provider and model for each action independently. Saved choices apply to new runs. API credentials stay on the server; model access is checked when a run starts.</p>
    {error ? <div><p role="alert" style={{ color: 'var(--red, #dc2626)' }}>{error}</p><button onClick={() => setRetry(value => value + 1)}>Reload AI settings</button></div>
      : !data ? <p>Loading AI settings…</p>
      : data.actions.filter(action => action.action !== 'draft_review').map(action => <ActionModelSettings key={action.action} settings={action} canConfigure={data.can_configure} />)}
    <DraftReviewSettings />
    <ProductSettings />
    <DocumentationProfiles />
    <AIInstructions />
  </div>;
}

Object.assign(window, { AISettings, draftReviewProviderName });
