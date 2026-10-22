const profileStyle = {
  section: { padding: 20, marginBottom: 20, border: '1px solid var(--rule, var(--line))', borderRadius: 6 },
  field: { display: 'grid', gap: 6, margin: '14px 0' },
  input: { width: '100%', boxSizing: 'border-box', padding: 9, color: 'var(--ink)', background: 'var(--surface-2, var(--paper))', border: '1px solid var(--rule, var(--line))', borderRadius: 4 },
  buttons: { display: 'flex', flexWrap: 'wrap', gap: 8, margin: '12px 0' },
  button: { padding: '8px 12px', color: 'var(--ink)', background: 'var(--surface-2, var(--paper))', border: '1px solid var(--rule, var(--line))', borderRadius: 4 },
};

async function profileRequest(path, method = 'GET', body) {
  const response = await fetch(path, { method, headers: { 'content-type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  const data = await response.json();
  if (!response.ok) throw new Error(response.status === 409
    ? 'This configuration changed elsewhere. Your edits are still here. Reload before saving again.'
    : typeof data.detail === 'string' ? data.detail : 'Could not save. Check the names and text, then try again.');
  return data;
}

function PromptHistory({ type, name, canRestore, onRestored, onBusyChange }) {
  const [versions, setVersions] = React.useState(null);
  const [selected, setSelected] = React.useState('');
  const [error, setError] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [reload, setReload] = React.useState(0);
  React.useEffect(() => {
    let active = true;
    setVersions(null); setError(null);
    profileRequest(`/api/documentation/prompts/history?type=${encodeURIComponent(type)}&name=${encodeURIComponent(name)}`)
      .then(data => { if (active) { setVersions(data.versions); setSelected(String(data.versions[0]?.version || '')); } })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [type, name, reload]);
  const version = versions?.find(item => String(item.version) === selected);
  const restore = async () => {
    onBusyChange?.(true);
    setBusy(true); setError(null);
    try {
      const saved = await profileRequest('/api/documentation/prompts/restore', 'POST', { type, name, version: version.version, revision: versions[0].version });
      setVersions(previous => [saved, ...previous.filter(item => item.version !== saved.version)]);
      setSelected(String(saved.version));
      await onRestored(saved);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); onBusyChange?.(false); }
  };
  return <section style={profileStyle.section} aria-label={`History of ${name}`}>
    <h3>History: {name}</h3>
    {error && <p role="alert">{error}</p>}
    {!versions ? <p>Loading history…</p> : versions.length === 0 ? <p>No saved versions.</p> : <>
      <label style={profileStyle.field}>Version<select value={selected} disabled={busy} style={profileStyle.input} onChange={event => setSelected(event.target.value)}>
        {versions.map(item => <option key={item.id} value={item.version}>Version {item.version} · {item.created_at} · {item.created_by || 'Unknown author'}{item.deleted ? ' · Retired' : ''}</option>)}
      </select></label>
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 320, overflow: 'auto' }}>{version?.deleted ? 'This version retired the text.' : version?.text}</pre>
      {canRestore && <button type="button" style={profileStyle.button} disabled={busy || !version || version.deleted || version.version === versions[0].version} onClick={restore}>{busy ? 'Restoring…' : 'Restore this version'}</button>}
      <p>Restored text becomes current. Earlier versions remain available.</p>
    </>}
    <button type="button" style={profileStyle.button} disabled={busy} onClick={() => setReload(value => value + 1)}>Reload history</button>
  </section>;
}

function DocumentationProfiles() {
  const [data, setData] = React.useState(null);
  const [form, setForm] = React.useState(null);
  const [original, setOriginal] = React.useState(null);
  const [creating, setCreating] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [message, setMessage] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [history, setHistory] = React.useState(null);
  const [retry, setRetry] = React.useState(0);
  const [showRetired, setShowRetired] = React.useState(false);
  React.useEffect(() => {
    let active = true;
    profileRequest('/api/documentation/profiles').then(value => { if (active) setData(value); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [retry]);
  const dirty = form && JSON.stringify(form) !== JSON.stringify(original);
  const choose = profile => {
    if (dirty && !window.confirm('Discard unsaved profile changes?')) return;
    setForm(profile); setOriginal(profile); setCreating(false); setHistory(null); setError(null); setMessage(null);
  };
  const create = source => {
    if (dirty && !window.confirm('Discard unsaved profile changes?')) return;
    const value = { name: source ? `${source.name}-copy` : '', revision: '', guidance: source?.guidance || '', exposure: source?.exposure || '', templates: source ? source.templates.map(item => ({ ...item })) : [] };
    setForm(value); setOriginal(null); setCreating(true); setHistory(null); setError(null); setMessage(null);
  };
  const change = (key, value) => { setForm(previous => ({ ...previous, [key]: value })); setMessage(null); };
  const reloadProfile = async () => {
    if (!form || creating) return;
    if (dirty && !window.confirm('Discard local edits and load the saved profile?')) return;
    setBusy(true); setError(null);
    try {
      const value = await profileRequest(`/api/documentation/profiles/${encodeURIComponent(form.name)}`);
      setForm(value); setOriginal(value); setRetry(value => value + 1);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const save = async event => {
    event.preventDefault(); setBusy(true); setError(null); setMessage(null);
    try {
      const value = await profileRequest(`/api/documentation/profiles/${encodeURIComponent(form.name)}`, 'PUT', { revision: form.revision, guidance: form.guidance, exposure: form.exposure, templates: form.templates.map(({ name, text }) => ({ name, text })) });
      setForm(value); setOriginal(value); setCreating(false); setRetry(value => value + 1); setMessage('Profile saved. New runs use these settings.');
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const retire = async () => {
    if (!window.confirm(`Retire ${form.name}? Its history and generated documents will remain.`)) return;
    setBusy(true); setError(null);
    try {
      const value = await profileRequest(`/api/documentation/profiles/${encodeURIComponent(form.name)}`, 'DELETE', { revision: form.revision });
      setForm(value); setOriginal(value); setRetry(value => value + 1); setMessage('Profile retired. It will stay retired after a restart.');
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const templateChange = (index, key, value) => change('templates', form.templates.map((item, i) => i === index ? { ...item, [key]: value } : item));
  const duplicateTemplate = item => {
    setForm(previous => {
      const names = new Set(previous.templates.map(template => template.name));
      const base = `${item.name}-copy`;
      let name = base;
      let suffix = 2;
      while (names.has(name)) name = `${base}-${suffix++}`;
      return { ...previous, templates: [...previous.templates, { name, text: item.text, isNew: true }] };
    });
    setMessage(null);
  };
  return <section style={profileStyle.section} aria-label="Documentation profiles">
    <h2>Documentation profiles</h2>
    <p>Configure writing guidance, disclosure rules, and document templates. Changes are stored here and need no deployment. Audience guidance does not change who can access generated documents.</p>
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {!data ? <p>Loading profiles…</p> : <>
      <div style={profileStyle.buttons}>
        {data.can_write && <button type="button" style={profileStyle.button} disabled={busy} onClick={() => create(null)}>Create profile</button>}
        <button type="button" style={profileStyle.button} disabled={busy} onClick={() => { setError(null); setRetry(value => value + 1); }}>Refresh profiles</button>
        <label><input type="checkbox" checked={showRetired} onChange={event => setShowRetired(event.target.checked)} /> Show retired profiles</label>
      </div>
      <div style={profileStyle.buttons}>{data.profiles.filter(item => showRetired || !item.retired).map(item => <button type="button" key={item.name} style={profileStyle.button} disabled={busy} onClick={() => choose(item)}>{item.name}{item.name === data.default_profile ? ' · Default' : ''}{item.retired ? ' · Retired' : !item.ready ? ' · Incomplete' : ''}</button>)}</div>
      {data.profiles.length === 0 && <p>No profiles yet. Create a profile and add a template to start.</p>}
      {form && <>
        {!creating && <h3>{form.name}{form.retired ? ' (retired)' : ''}</h3>}
        {!creating && form.issues?.map(issue => <p key={issue}>{issue}</p>)}
        <form onSubmit={save}><fieldset disabled={busy || !data.can_write} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
          {creating && <label style={profileStyle.field}>Profile name<input style={profileStyle.input} value={form.name} onChange={event => change('name', event.target.value)} required maxLength={200} pattern="[^/]+" placeholder="For example internal-doc" /></label>}
          <label style={profileStyle.field}>Writing guidance<textarea rows={8} style={profileStyle.input} value={form.guidance} onChange={event => change('guidance', event.target.value)} /></label>
          {!creating && <button type="button" style={profileStyle.button} onClick={() => setHistory('guidance')}>Guidance history</button>}
          <label style={profileStyle.field}>Disclosure rules<textarea rows={6} style={profileStyle.input} value={form.exposure} onChange={event => change('exposure', event.target.value)} placeholder="Describe what may be disclosed and what must remain internal." /></label>
          {!creating && <button type="button" style={profileStyle.button} onClick={() => setHistory('exposure')}>Disclosure history</button>}
          <h3>Document templates</h3>
          {form.templates.length === 0 && <p>Add a template to make this profile available for generation.</p>}
          {form.templates.map((item, index) => <section key={index} style={profileStyle.section}>
            <label style={profileStyle.field}>Template name<input style={profileStyle.input} value={item.name} required maxLength={200} pattern="[^/]+" disabled={!creating && !item.isNew} onChange={event => templateChange(index, 'name', event.target.value)} /></label>
            <label style={profileStyle.field}>Template text<textarea rows={10} style={profileStyle.input} value={item.text} required onChange={event => templateChange(index, 'text', event.target.value)} /></label>
            <div style={profileStyle.buttons}>
              {!creating && !item.isNew && <button type="button" style={profileStyle.button} onClick={() => setHistory(item.name)}>Template history</button>}
              <button type="button" style={profileStyle.button} onClick={() => duplicateTemplate(item)}>Duplicate template</button>
              {(data.can_retire || creating || item.isNew) && <button type="button" style={profileStyle.button} onClick={() => change('templates', form.templates.filter((_, i) => i !== index))}>Remove template</button>}
            </div>
          </section>)}
          <div style={profileStyle.buttons}>
            <button type="button" style={profileStyle.button} onClick={() => change('templates', [...form.templates, { name: '', text: '', isNew: true }])}>Add template</button>
            <button type="submit" style={profileStyle.button}>{busy ? 'Saving…' : 'Save profile'}</button>
          </div>
        </fieldset></form>
        <div style={profileStyle.buttons}>
          {!creating && <button type="button" style={profileStyle.button} disabled={busy} onClick={reloadProfile}>Reload saved profile</button>}
          {data.can_write && <button type="button" style={profileStyle.button} disabled={busy} onClick={() => create(form)}>Duplicate profile</button>}
          {data.can_retire && !creating && !form.retired && <button type="button" style={profileStyle.button} disabled={busy || form.name === data.default_profile} onClick={retire}>Retire profile</button>}
        </div>
        {form.name === data.default_profile && <p>Choose another default under Documentation delivery before retiring this profile or its last template.</p>}
        {!data.can_write && <p>Writers can edit these profiles. Administrators can retire them.</p>}
        {!creating && <label style={profileStyle.field}>Text history<select style={profileStyle.input} disabled={busy} value={history || ''} onChange={event => setHistory(event.target.value || null)}>
          <option value="">Choose text to inspect</option><option value="guidance">Writing guidance</option><option value="exposure">Disclosure rules</option>
          {original?.templates.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}
          {original?.retired_templates?.map(name => <option key={name} value={name}>{name} (retired)</option>)}
        </select></label>}
        {history && !creating && <><p>{dirty ? 'Save or reload your edits before restoring history.' : ''}</p><PromptHistory key={`${form.name}/${history}`} type="guideline-set" name={`${form.name}/${history}`} canRestore={data.can_write && !dirty && !busy} onBusyChange={setBusy} onRestored={reloadProfile} /></>}
      </>}
    </>}
    {!data && <button type="button" style={profileStyle.button} onClick={() => { setError(null); setRetry(value => value + 1); }}>Retry loading profiles</button>}
  </section>;
}

function AIInstructions() {
  const [options, setOptions] = React.useState(null);
  const [name, setName] = React.useState('ask');
  const [head, setHead] = React.useState(null);
  const [defaultText, setDefaultText] = React.useState('');
  const [text, setText] = React.useState('');
  const [preview, setPreview] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [message, setMessage] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [reload, setReload] = React.useState(0);
  const [history, setHistory] = React.useState(false);
  React.useEffect(() => {
    let active = true;
    profileRequest('/api/ai-instructions').then(value => { if (active) setOptions(value); })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [reload]);
  React.useEffect(() => {
    let active = true;
    setHead(null); setText(''); setPreview(null); setHistory(false);
    profileRequest(`/api/ai-instructions/${encodeURIComponent(name)}`)
      .then(value => {
        if (active) {
          setHead(value.current); setText(value.current.text);
          setDefaultText(value.default_text); setPreview(value.preview);
        }
      }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [name, reload]);
  const dirty = head && text !== head.text;
  const refresh = () => {
    if (dirty && !window.confirm('Discard unsaved instruction changes?')) return;
    setError(null); setReload(value => value + 1);
  };
  const applySaved = saved => {
    setHead({ version: saved.version, text: saved.text, source: 'saved' });
    setText(saved.text); setPreview(null);
    setMessage('Instructions saved. New runs use this version; running actions keep their captured instructions.');
  };
  const save = async event => {
    event.preventDefault(); setBusy(true); setError(null); setMessage(null);
    try {
      const saved = await profileRequest('/api/documentation/prompts', 'PUT', { type: 'doctrine', name, text, revision: head.version });
      applySaved(saved);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const inspect = async () => {
    setBusy(true); setError(null);
    try {
      const value = await profileRequest(`/api/ai-instructions/${encodeURIComponent(name)}/preview`, 'POST', { text });
      setPreview(value.preview);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const edit = value => { setText(value); setPreview(null); setMessage(null); };
  return <section style={profileStyle.section} aria-label="Prompts">
    <h2>Prompts</h2>
    <p>View and edit the behavioral instructions for each AI action. Both providers use these instructions. Saves keep a version history and take effect on new runs.</p>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    <label style={profileStyle.field}>AI action<select value={name} style={profileStyle.input} disabled={busy || !options} onChange={event => {
      if (!dirty || window.confirm('Discard unsaved instruction changes?')) { setName(event.target.value); setError(null); setMessage(null); }
    }}>
      {(options?.actions || [{ name: 'ask', title: 'Questions' }]).map(item => <option key={item.name} value={item.name}>{item.title}</option>)}
    </select></label>
    {!head ? <p>Loading instructions…</p> : <>
      {head.note && <p role="alert">{head.note}</p>}
      <p>{head.source === 'saved' ? `Saved version ${head.version}` : 'Using default instructions'}{dirty ? ' · Unsaved changes' : ''}</p>
      <form onSubmit={save}>
        <label style={profileStyle.field}>Behavioral instructions<textarea rows={14} style={profileStyle.input} value={text}
          readOnly={!options?.can_write} disabled={busy} onChange={event => edit(event.target.value)} required /></label>
        <div style={profileStyle.buttons}>
          {options?.can_write && <>
            <button type="submit" style={profileStyle.button} disabled={busy || !dirty || !text.trim()}>Save instructions</button>
            <button type="button" style={profileStyle.button} disabled={busy || text === defaultText}
              onClick={() => { if (!dirty || window.confirm('Replace unsaved changes with the shipped default?')) edit(defaultText); }}>Use shipped default</button>
          </>}
          <button type="button" style={profileStyle.button} disabled={busy} onClick={inspect}>Preview combined prompt</button>
        </div>
      </form>
      <p>Using the shipped default fills the editor; save to apply it. Tool schemas, response formats, and application safeguards remain controlled by code.</p>
      {(name === 'docgen' || name === 'document_review') && <p>Documentation profiles below control writing guidance, disclosure rules, and templates. The preview marks where the selected profile will be inserted.</p>}
      <p>The preview shows the system instructions. Request text, retrieved evidence, tool definitions, and loop messages are supplied separately during a run.</p>
      {preview !== null && <details><summary>Combined prompt preview</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 420, overflow: 'auto' }}>{preview}</pre></details>}
      <button type="button" style={profileStyle.button} disabled={busy} onClick={() => setHistory(value => !value)}>Version history</button>
      {history && <PromptHistory key={`${name}/${head.version}`} type="doctrine" name={name}
        canRestore={options?.can_write && !dirty && !busy} onBusyChange={setBusy} onRestored={applySaved} />}
      {history && dirty && <p>Save or reload your edits before restoring history.</p>}
    </>}
    <button type="button" style={profileStyle.button} disabled={busy} onClick={refresh}>Reload instructions</button>
  </section>;
}

Object.assign(window, { DocumentationProfiles, AIInstructions });
