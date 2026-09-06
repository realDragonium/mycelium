async function docRequest(path, body, signal) {
  const response = await fetch('/api/documentation/' + path, {
    method: body === undefined ? 'GET' : 'POST', signal,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'The request could not be completed. Check the values and try again.');
  return value;
}

function docRoute() {
  const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
  return { tab: params.get('tab') || (params.has('run') ? 'runs' : 'library'), document: params.get('document'), revision: params.get('revision'), run: params.get('run') };
}

function docNavigate(next) {
  const params = new URLSearchParams();
  Object.entries(next).forEach(([key, value]) => { if (value) params.set(key, value); });
  const query = params.toString();
  window.location.hash = '/documentation' + (query ? '?' + query : '');
}

const docActive = run => ['queued', 'running'].includes(run.status);
const docStatus = status => ({ queued: 'Queued', running: 'Generating and reviewing', document_written: 'Saved', document_superseded: 'Saved · newer revision exists', nothing_written: 'No document saved', failed: 'Failed' }[status] || status);
const docDeliveryStatus = status => ({ unpublished: 'Internal only', published: 'Published to GitHub', changes_pending: 'Changes awaiting publication' }[status] || status);
const docDate = value => value ? new Date(value).toLocaleString() : 'Not recorded';

function DocumentationModel({ options, value, onChange, disabled }) {
  return <label>Model for this run<select value={value} onChange={event => onChange(event.target.value)} disabled={disabled}>
    {options.models.map(model => <option key={model.provider} value={model.provider} disabled={!model.available}>{model.label} · {model.model}{model.available ? '' : ' (unavailable)'}</option>)}
  </select></label>;
}

function DocumentationGenerator({ options, document, onStarted }) {
  const [prompt, setPrompt] = React.useState('');
  const [provider, setProvider] = React.useState(options.default_provider);
  const providerChosen = React.useRef(false);
  React.useEffect(() => { if (!providerChosen.current) setProvider(options.default_provider); }, [options.default_provider]);
  const [profile, setProfile] = React.useState('');
  const [type, setType] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const submitting = React.useRef(false);
  const selected = options.models.find(model => model.provider === provider);
  const allowed = options.can_generate && selected?.available;
  const submit = async event => {
    event.preventDefault();
    if (submitting.current || !allowed || !prompt.trim()) return;
    submitting.current = true; setBusy(true); setError(null);
    try {
      const run = await docRequest(document ? `documents/${encodeURIComponent(document.id)}/revisions` : 'runs', document
        ? { prompt: prompt.trim(), provider, expected_revision: document.current_revision }
        : { prompt: prompt.trim(), provider, guideline_set: profile || null, document_type: type || null });
      onStarted(run);
    } catch (error) { setError(error.message); }
    finally { submitting.current = false; setBusy(false); }
  };
  return <form onSubmit={submit} className="docw-panel">
    <h2>{document ? `Create revision of “${document.title}”` : 'Generate a document'}</h2>
    <p>{document ? `This uses internal revision ${document.current_revision}. The previous version stays in history.` : 'Describe the concept, audience, and scope. The result is saved internally for review before you publish it.'}</p>
    <fieldset disabled={busy || !options.can_generate}>
      <DocumentationModel options={options} value={provider} onChange={value => { providerChosen.current = true; setProvider(value); }} />
      {!document && <div className="docw-fields">
        <label>Writing profile<select value={profile} onChange={event => { setProfile(event.target.value); setType(''); }}><option value="">Choose automatically</option>{Object.keys(options.guideline_sets).map(name => <option key={name}>{name}</option>)}</select></label>
        <label>Document template<select value={type} disabled={!profile} onChange={event => setType(event.target.value)}><option value="">Choose automatically</option>{(options.guideline_sets[profile] || []).map(name => <option key={name}>{name}</option>)}</select></label>
      </div>}
      <label>{document ? 'What should change?' : 'What should be documented?'}<textarea required maxLength={options.max_prompt_chars} value={prompt} onChange={event => setPrompt(event.target.value)} placeholder={document ? 'Explain what to improve, add, or remove.' : 'For example: Explain invitation reminders for administrators, including setup and examples.'} /></label>
      <button type="submit" disabled={!allowed || !prompt.trim()}>{busy ? 'Starting…' : document ? 'Generate next revision' : 'Generate document'}</button>
    </fieldset>
    {!options.can_generate && <p>Writer or admin access is required to generate and publish documents.</p>}
    {!selected?.available && <p>The selected provider needs server credentials before it can run.</p>}
    {error && <p role="alert">{error}</p>}
  </form>;
}

function DocumentationDelivery({ document, canWrite, onUpdated, onConfigure }) {
  const [destinations, setDestinations] = React.useState([]);
  const [destination, setDestination] = React.useState(document.delivery_destination || '');
  const [loadError, setLoadError] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [retry, setRetry] = React.useState(0);
  const submitting = React.useRef(false);
  React.useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    docRequest('destinations').then(value => { if (!cancelled) setDestinations(value.destinations); }).catch(error => { if (!cancelled) setLoadError(error.message); });
    return () => { cancelled = true; };
  }, [retry]);
  const selected = destinations.find(item => item.name === destination);
  const coordinates = document.delivery_coordinates || selected?.coordinates;
  const reference = document.delivery_reference;
  const publish = async () => {
    if (submitting.current || !destination) return;
    submitting.current = true; setBusy(true); setError(null);
    try {
      await docRequest(`documents/${encodeURIComponent(document.id)}/delivery`, { destination, expected_revision: document.current_revision });
      onUpdated();
    } catch (error) { setError(error.message); }
    finally { submitting.current = false; setBusy(false); }
  };
  return <section className="docw-panel" aria-label="GitHub publication">
    <h2>GitHub publication</h2>
    <p role="status">{docDeliveryStatus(document.delivery_status)}{document.published_revision ? ` · last published revision ${document.published_revision}` : ''}</p>
    {typeof reference === 'string' && /^https:\/\//i.test(reference) && <p><a href={reference} target="_blank" rel="noopener noreferrer">Open GitHub pull request ↗</a></p>}
    <label>Destination<select value={destination} disabled={!canWrite || busy || !!document.delivery_destination} onChange={event => setDestination(event.target.value)}>
      <option value="">Select a destination</option>
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

function DocumentationDocument({ id, revision, options, onStarted, refresh, onUpdated }) {
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [retry, setRetry] = React.useState(0);
  const [source, setSource] = React.useState(false);
  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    setData(null); setError(null);
    const path = `documents/${encodeURIComponent(id)}`;
    Promise.all([docRequest(path, undefined, controller.signal), docRequest(path + '/revisions', undefined, controller.signal), revision ? docRequest(path + '/revisions/' + encodeURIComponent(revision), undefined, controller.signal) : Promise.resolve(null)])
      .then(([current, history, selected]) => { if (!cancelled) setData({ current, history: history.revisions, selected: selected || current }); })
      .catch(error => { if (!cancelled) setError(error.message); });
    return () => { cancelled = true; controller.abort(); };
  }, [id, revision, refresh, retry]);
  if (error) return <div role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>Reload document</button></div>;
  if (!data) return <p role="status">Loading document…</p>;
  const { current, history, selected } = data;
  const historical = revision && Number(revision) !== current.current_revision;
  const download = () => {
    const url = URL.createObjectURL(new Blob([selected.body], { type: 'text/markdown;charset=utf-8' }));
    const link = window.document.createElement('a'); link.href = url; link.download = selected.slug + '.md'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <>
    <section className="docw-panel">
      <button onClick={() => docNavigate({ tab: 'library' })}>← All documents</button>
      <h2>{selected.title}</h2><p className="docw-meta">{selected.guideline_set} · {selected.document_type} · revision {revision || current.current_revision}</p>
      <label>Revision history<select value={revision || current.current_revision} onChange={event => docNavigate({ document: id, revision: event.target.value })}>{history.map(item => <option key={item.revision} value={item.revision}>Revision {item.revision}{item.revision === current.current_revision ? ' (current)' : ''} · {docDate(item.created_at)}</option>)}</select></label>
      {historical && <p>You are reading an earlier revision. <button onClick={() => docNavigate({ document: id })}>Open current revision to edit or publish</button></p>}
      <div className="docw-actions"><button onClick={() => setSource(value => !value)}>{source ? 'Read document' : 'View Markdown'}</button><button onClick={download}>Download Markdown</button></div>
      {source ? <pre className="docw-source">{selected.body}</pre> : <article className="docw-prose" dangerouslySetInnerHTML={{ __html: selected.body_html }} />}
      <details><summary>Sources and review</summary><p>{selected.statement_ids?.length || 0} source statements</p><ul>{(selected.statement_ids || []).map(id => <li key={id}><a href={'/ui/#/b/' + encodeURIComponent(id)}>{id}</a></li>)}</ul><pre className="docw-source">{JSON.stringify(selected.review, null, 2)}</pre></details>
      {(selected.run_id || (!historical && current.last_run_id)) && <p><button onClick={() => docNavigate({ run: selected.run_id || current.last_run_id })}>View generation run</button></p>}
    </section>
    {!historical && <><DocumentationDelivery key={current.current_revision} document={current} canWrite={options.can_generate} onUpdated={onUpdated} onConfigure={() => docNavigate({ tab: 'settings' })} /><DocumentationGenerator key={current.id + ':' + current.current_revision} options={options} document={current} onStarted={onStarted} /></>}
  </>;
}

function DocumentationRun({ id, onCompleted }) {
  const [run, setRun] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [retry, setRetry] = React.useState(0);
  React.useEffect(() => {
    let cancelled = false, timer;
    const controller = new AbortController();
    setRun(null); setError(null);
    const load = async () => {
      try {
        const value = await docRequest('runs/' + encodeURIComponent(id), undefined, controller.signal);
        if (cancelled) return;
        setRun(value); setError(null);
        if (docActive(value)) timer = setTimeout(load, 2500);
        else onCompleted();
      } catch (error) { if (!cancelled) setError(error.message); }
    };
    load(); return () => { cancelled = true; controller.abort(); clearTimeout(timer); };
  }, [id, retry, onCompleted]);
  if (error) return <p role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>Reload run</button></p>;
  if (!run) return <p role="status">Loading run…</p>;
  return <section className="docw-panel" aria-label="Generation run"><h2>{docStatus(run.status)}</h2><p className="docw-meta">{run.provider} · {run.model} · {docDate(run.created_at)}</p><p>{run.prompt}</p>
    {docActive(run) && <p role="status">You can leave this screen while generation and review finish.</p>}
    {run.error && <p role="alert">{run.error}</p>}
    {run.document_id && <button onClick={() => docNavigate({ document: run.document_id, revision: run.result_revision })}>{run.result_revision ? `Read saved revision ${run.result_revision}` : 'Open document'}</button>}
    {run.document_id && !run.result_revision && <p>This older run has no retained revision snapshot. The link opens the current document.</p>}
    {run.draft_body && <details open><summary>Unsaved draft · {run.draft_title}</summary><pre className="docw-source">{run.draft_body}</pre></details>}
  </section>;
}

function DocumentationConfiguration() {
  const [models, setModels] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [retry, setRetry] = React.useState(0);
  React.useEffect(() => {
    let cancelled = false;
    setError(null);
    fetch('/api/model-settings').then(async response => {
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'Could not load models.');
      if (!cancelled) setModels(value);
    }).catch(error => { if (!cancelled) setError(error.message); });
    return () => { cancelled = true; };
  }, [retry]);
  return <section className="docw-panel"><h2>Documentation settings</h2><p>Choose the model, generation limits, default writing profile, and GitHub repositories. Credentials are managed on the server; repository settings choose an approved connection.</p>
    {error && <p role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>Reload models</button></p>}
    {models?.actions.filter(action => action.action === 'docgen').map(action => <ActionModelSettings key={action.action} settings={action} canConfigure={models.can_configure} />)}
    <ProductSettings kinds={['documentation', 'docgen']} />
  </section>;
}

function DocumentationWorkspace() {
  const [route, setRoute] = React.useState(docRoute);
  const [options, setOptions] = React.useState(null);
  const [documents, setDocuments] = React.useState([]);
  const [runs, setRuns] = React.useState([]);
  const [error, setError] = React.useState(null);
  const [refresh, setRefresh] = React.useState(0);
  const [search, setSearch] = React.useState('');
  const update = React.useCallback(() => setRefresh(value => value + 1), []);
  React.useEffect(() => {
    const change = () => setRoute(docRoute());
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  React.useEffect(() => {
    let cancelled = false, timer;
    const controller = new AbortController();
    setError(null);
    const load = async () => {
      try {
        const [options, library, history] = await Promise.all([docRequest('options', undefined, controller.signal), docRequest('documents', undefined, controller.signal), docRequest('runs', undefined, controller.signal)]);
        if (cancelled) return;
        setOptions(options); setDocuments(library.documents); setRuns(history.runs); setError(null);
        if (history.runs.some(docActive)) timer = setTimeout(load, 2500);
      } catch (error) { if (!cancelled) setError(error.message); }
    };
    load(); return () => { cancelled = true; controller.abort(); clearTimeout(timer); };
  }, [refresh, route.tab]);
  const started = run => { update(); docNavigate({ run: run.id }); };
  const filtered = documents.filter(document => [document.title, document.guideline_set, document.document_type].join(' ').toLowerCase().includes(search.toLowerCase()));
  return <main className="docw"><header><h1>Documentation</h1><p>Write, refine, and publish documents from your knowledge base.</p></header>
    <nav className="docw-tabs" aria-label="Documentation sections">{[['library', 'Documents'], ['generate', 'Generate'], ['runs', 'Generation history'], ['profiles', 'Profiles & templates'], ['settings', 'Models & GitHub']].map(([tab, label]) => <button key={tab} aria-current={route.tab === tab ? 'page' : undefined} onClick={() => docNavigate({ tab })}>{label}</button>)}</nav>
    {error && <p role="alert">{error} <button onClick={update}>Reload documentation</button></p>}
    {route.tab === 'profiles' ? <section className="docw-panel"><DocumentationProfiles /></section> : route.tab === 'settings' ? <DocumentationConfiguration /> : !options ? !error && <p role="status">Loading documentation…</p> : <>
      {route.tab === 'generate' && <DocumentationGenerator options={options} onStarted={started} />}
      {route.tab === 'library' && (route.document ? <DocumentationDocument key={route.document} id={route.document} revision={route.revision} options={options} refresh={refresh} onUpdated={update} onStarted={started} /> : <section className="docw-panel">
        <div className="docw-actions"><h2>Saved documents</h2><button onClick={() => docNavigate({ tab: 'generate' })}>Generate document</button><button onClick={update}>Refresh</button></div>
        <p>Documents and their revisions are stored in Mycelium and included in instance backups.</p>
        <label>Find a document<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Title, profile, or template" /></label>
        {!documents.length ? <p>No documents yet. Start with Generate, or configure a writing profile first.</p> : !filtered.length ? <p>No documents match this search.</p> : <div className="docw-list">{filtered.map(document => <button key={document.id} onClick={() => docNavigate({ document: document.id })}><strong>{document.title}</strong><span>{document.guideline_set} · {document.document_type} · revision {document.current_revision}</span><span>{docDeliveryStatus(document.delivery_status)} · updated {docDate(document.updated_at)}</span></button>)}</div>}
      </section>)}
      {route.tab === 'runs' && <>{route.run && <DocumentationRun key={route.run} id={route.run} onCompleted={update} />}<section className="docw-panel"><div className="docw-actions"><h2>Recent generation runs</h2><button onClick={update}>Refresh</button></div>{!runs.length ? <p>No runs yet.</p> : <div className="docw-list">{runs.map(run => <button key={run.id} onClick={() => docNavigate({ run: run.id })}><strong>{run.prompt}</strong><span>{docStatus(run.status)} · {run.provider} · {docDate(run.created_at)}</span></button>)}</div>}</section></>}
    </>}
  </main>;
}

Object.assign(window, { DocumentationWorkspace });
