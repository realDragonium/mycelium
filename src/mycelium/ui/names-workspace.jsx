async function namesRequest(path = '', body, signal) {
  const response = await fetch('/api/names-workspace' + path, {
    method: body === undefined ? 'GET' : 'POST', signal,
    headers: body === undefined ? undefined : {'content-type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const recovery = `Request failed (${response.status}). Check the values and try again.`;
  let data;
  try {
    data = await response.json();
  } catch (error) {
    if (!response.ok) throw new Error(recovery);
    throw error;
  }
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : recovery);
  return data;
}

function NamesExamples({examples, count}) {
  return <div><p>{count} possible text matches{count > examples.length ? `, showing ${examples.length}` : ''}. These are examples, not confirmed references.</p>
    <ul className="names-examples">{examples.map(item => <li key={item.id}><p>{item.text}</p><small>{item.kind} · {item.id}</small></li>)}</ul></div>;
}

function NamesRelationships({items, entities}) {
  const label = id => entities.find(entity => entity.id === id)?.label || id;
  return items.length ? <ul>{items.map((item, index) => <li key={index}>{item.family === 'statement' && item.source.startsWith('stm_') ? item.statement_text : label(item.source)} → {item.link_type} → {item.family === 'statement' && item.target.startsWith('stm_') ? item.statement_text : label(item.target)}{item.condition && <pre>Condition: {JSON.stringify(item.condition)}</pre>}</li>)}</ul> : <p>No concept relationships.</p>;
}

function NamesEditor({entity, entities, allowedActions, onChanged}) {
  const [kind, setKind] = React.useState('add');
  const [nameId, setNameId] = React.useState('');
  const [text, setText] = React.useState('');
  const [target, setTarget] = React.useState('');
  const [selected, setSelected] = React.useState([]);
  const [preferred, setPreferred] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [preview, setPreview] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const inFlight = React.useRef(false);
  const authored = entity.names.filter(name => !name.generated_from_name_id);
  const destination = entities.find(item => item.id === target);
  const preferredOptions = kind === 'merge' ? [...authored, ...(destination?.names || []).filter(name => !name.generated_from_name_id)] : authored.filter(name => selected.includes(name.id));
  const changeKind = value => { setKind(value); setPreview(null); setError(null); setNameId(''); setText(''); setPreferred(''); setSelected([]); setTarget(''); setDescription(''); };
  const change = setter => event => { setter(event.target.value); setPreview(null); setError(null); };
  const action = () => {
    const base = {kind, entity_id: entity.id};
    if (kind === 'add') return {...base, text};
    if (kind === 'correct') return {...base, name_id: nameId, text};
    if (kind === 'move') return {...base, name_id: nameId, target_entity_id: target};
    if (kind === 'split') return {...base, name_ids: selected, preferred_name_id: preferred, description};
    if (kind === 'merge') return {...base, target_entity_id: target, preferred_name_id: preferred, description};
    return {...base, name_id: nameId};
  };
  const run = async apply => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(null);
    try {
      if (apply) { const result = await namesRequest('/apply', {action: preview.action, expected_revision: preview.revision}); setPreview(null); onChanged(result.entity_id); }
      else setPreview(await namesRequest('/preview', {action: action()}));
    } catch (error) { setError(error.message); if (apply) setPreview(null); }
    finally { inFlight.current = false; setBusy(false); }
  };
  return <section className="names-panel"><h3>Edit names</h3>{!allowedActions.includes("merge") && <p>Admin access is required to merge concepts or remove aliases.</p>}
    <form onSubmit={event => {event.preventDefault(); run(false);}}><fieldset disabled={busy}>
      <label>Action<select aria-label="Action" value={kind} onChange={event => changeKind(event.target.value)}>
        <option value="add">Add alias</option><option value="correct">Correct spelling</option><option value="prefer">Change preferred name</option><option value="move">Move alias to another concept</option><option value="split">Split names into a new concept</option><option value="merge" disabled={!allowedActions.includes("merge")}>Merge into another concept{allowedActions.includes("merge") ? "" : " (admin required)"}</option><option value="remove" disabled={!allowedActions.includes("remove")}>Remove alias{allowedActions.includes("remove") ? "" : " (admin required)"}</option>
      </select></label>
      {['correct','prefer','move','remove'].includes(kind) && <label>Name<select aria-label="Name" required value={nameId} onChange={event => {setNameId(event.target.value); setPreview(null); if (kind === 'correct') setText(authored.find(name => name.id === event.target.value)?.text || '');}}><option value="">Choose a name</option>{authored.map(name => <option key={name.id} value={name.id}>{name.text}</option>)}</select></label>}
      {['add','correct'].includes(kind) && <label>{kind === 'add' ? 'New alias' : 'Corrected spelling'}<input required maxLength={500} value={text} onChange={change(setText)} /></label>}
      {kind === 'prefer' && <p>To use a new name, add it as an alias first. Choosing a preferred name keeps all existing aliases.</p>}
      {['move','merge'].includes(kind) && <label>Destination concept<select aria-label="Destination concept" required value={target} onChange={event => {setTarget(event.target.value); setPreview(null); setPreferred(''); if (kind === 'merge') setDescription(entities.find(item => item.id === event.target.value)?.description || '');}}><option value="">Choose a concept</option>{entities.filter(item => item.id !== entity.id).map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>}
      {kind === 'split' && <div><p>Names to move, including their generated plurals:</p>{authored.map(name => <label className="names-check" key={name.id}><input type="checkbox" checked={selected.includes(name.id)} onChange={event => {setSelected(previous => event.target.checked ? [...previous, name.id] : previous.filter(id => id !== name.id)); setPreferred(''); setPreview(null);}} />{name.text}</label>)}</div>}
      {['split','merge'].includes(kind) && <>
        <label>Preferred name<select aria-label="Preferred name" required value={preferred} onChange={change(setPreferred)}><option value="">Choose the displayed name</option>{preferredOptions.map(name => <option key={name.id} value={name.id}>{name.text}</option>)}</select></label>
        {kind === 'merge' && destination && <div className="names-description-choices"><button type="button" onClick={() => {setDescription(entity.description); setPreview(null);}}>Use source description</button><button type="button" onClick={() => {setDescription(destination.description); setPreview(null);}}>Use destination description</button></div>}
        <label>{kind === 'split' ? 'New concept description' : 'Surviving description'}<textarea aria-label={kind === 'split' ? 'New concept description' : 'Surviving description'} maxLength={20000} value={description} onChange={change(setDescription)} /></label>
      </>}
      <button type="submit">{busy ? 'Working…' : 'Preview change'}</button>
    </fieldset></form>
    {error && <p role="alert">{error}</p>}
    {preview && <div className="names-preview"><h3>Review change</h3><p>{preview.summary}</p>
      <p>Names: {preview.names.map(name => name.text).join(', ') || 'None'}</p>
      {['merge','split'].includes(preview.action.kind) && <p>Description: {preview.action.description || 'Empty description'}</p>}
      {preview.warnings.map(warning => <p key={warning}>{warning}</p>)}
      {preview.action.kind === 'merge' && <><h4>Relationships before</h4><NamesRelationships items={preview.relationships_before} entities={entities}/><h4>Relationships after</h4><NamesRelationships items={preview.relationships_after} entities={entities}/></>}
      <NamesExamples examples={preview.examples} count={preview.example_count}/>
      <button disabled={busy} onClick={() => run(true)}>Apply reviewed change</button><button disabled={busy} onClick={() => setPreview(null)}>Cancel</button>
    </div>}
  </section>;
}

function NamesDiscovery({entityId}) {
  const [after, setAfter] = React.useState(0);
  const [items, setItems] = React.useState([]);
  const [page, setPage] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [retry, setRetry] = React.useState(0);
  React.useEffect(() => {
    const controller = new AbortController(); setBusy(true); setError(null);
    fetch('/api/mention-candidates?' + new URLSearchParams({entity_id: entityId, after, limit: 30}), {signal: controller.signal})
      .then(async response => {const value = await response.json(); if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'Could not load statement matches.'); return value;})
      .then(value => {setItems(previous => after ? [...previous, ...value.matches] : value.matches); setPage(value);})
      .catch(error => {if (error.name !== 'AbortError') setError(error.message);})
      .finally(() => {if (!controller.signal.aborted) setBusy(false);});
    return () => controller.abort();
  }, [entityId, after, retry]);
  return <div><p>Names are matched against statement wording. Short or ambiguous matches remain possible references.</p>
    <ul className="names-examples">{items.map(item => <li key={item.statement_id}><p>{item.text}</p><small>{{derived: 'Recognized name', approved: 'Historically approved reference', possible: 'Possible reference'}[item.match]} · {item.names.map(name => name.text).join(', ')}</small></li>)}</ul>
    {!busy && !items.length && <p>No matching statements found in the scanned portion.</p>}
    {busy && <p>Finding statements…</p>}
    {error && <p role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
    {page?.has_more && !error && <button disabled={busy} onClick={() => setAfter(page.next_after)}>{items.length ? 'Find more matches' : 'Continue searching statements'}</button>}
  </div>;
}

function NamesConcept({id, entities, canWrite, allowedActions, refresh, onChanged}) {
  const [detail, setDetail] = React.useState(null);
  const [error, setError] = React.useState(null);
  React.useEffect(() => {
    const controller = new AbortController(); setDetail(null); setError(null);
    namesRequest('/' + encodeURIComponent(id), undefined, controller.signal).then(setDetail).catch(error => {if (error.name !== 'AbortError') setError(error.message);});
    return () => controller.abort();
  }, [id, refresh]);
  if (error) return <p role="alert">{error}</p>;
  if (!detail) return <p>Loading concept…</p>;
  const entity = detail.entity;
  return <div><section className="names-panel"><h2>{entity.label}</h2><p>{entity.description || 'No description.'}</p>
    <ul>{entity.names.map(name => <li key={name.id}><b>{name.text}</b>{name.id === entity.preferred_name_id ? ' · preferred' : ''}{name.generated_from_name_id ? ` · generated from ${entity.names.find(source => source.id === name.generated_from_name_id)?.text || 'another name'}` : ''}</li>)}</ul>
    <h3>Example statements</h3><NamesDiscovery key={id + ":" + refresh} entityId={id}/>
    <details><summary>Concept relationships ({detail.relationships.length})</summary><NamesRelationships items={detail.relationships} entities={entities}/></details>
  </section>
  {canWrite && <NamesEditor key={id + ':' + detail.revision} entity={entity} entities={entities} allowedActions={allowedActions} onChanged={onChanged}/>}
  <section className="names-panel"><h3>Change history</h3>{!detail.history_available ? <p>No history archive is attached.</p> : !detail.history.length ? <p>No recorded changes.</p> : <ul>{detail.history.map((item, index) => <li key={index}><details><summary>{new Date(item.at).toLocaleString()} · {item.op} · {item.actor || 'Actor not recorded'}</summary>{item.context_json && <pre>{item.context_json}</pre>}<p>Before</p><pre>{item.before_json || 'Not recorded'}</pre><p>After</p><pre>{item.after_json || 'Not recorded'}</pre></details></li>)}</ul>}</section></div>;
}

function NamesWorkspace({onDataChanged}) {
  const [catalogue, setCatalogue] = React.useState(null);
  const [selected, setSelected] = React.useState(null);
  const [query, setQuery] = React.useState('');
  const [tab, setTab] = React.useState('names');
  const [refresh, setRefresh] = React.useState(0);
  const [error, setError] = React.useState(null);
  const [notice, setNotice] = React.useState(null);
  React.useEffect(() => {
    const controller = new AbortController(); setError(null);
    namesRequest('', undefined, controller.signal).then(setCatalogue).catch(error => {if (error.name !== 'AbortError') setError(error.message);});
    return () => controller.abort();
  }, [refresh]);
  const changed = id => {if (id) setSelected(id); setRefresh(value => value + 1); setNotice('Change saved. Discovery is being recomputed.'); if (onDataChanged) onDataChanged().catch(() => setNotice('Change saved. Reload the page to refresh other views.'));};
  const filtered = (catalogue?.entities || []).filter(entity => (entity.label + ' ' + entity.description + ' ' + entity.names.map(name => name.text).join(' ')).toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const Suggestions = window.AliasSuggestions;
  return <main className="names-workspace"><h1>Names &amp; aliases</h1><p>Keep the names for each concept together. Statements keep their original wording.</p>
    <nav aria-label="Names workspace"><button aria-pressed={tab === 'names'} onClick={() => setTab('names')}>Names</button>{Suggestions && <button aria-pressed={tab === 'suggestions'} onClick={() => setTab('suggestions')}>AI suggestions</button>}</nav>
    {error && <p role="alert">{error} <button onClick={() => setRefresh(value => value + 1)}>Retry</button></p>}
    {notice && <p role="status">{notice}</p>}
    {!catalogue ? <p>Loading names…</p> : tab === 'suggestions' && Suggestions ? <Suggestions canWrite={catalogue.can_write} onChanged={() => changed()}/> : <>
      {!catalogue.can_write && <p>Writer or admin access is required to edit names.</p>}
      <div className="names-layout"><aside><label>Find a name or alias<input type="search" value={query} onChange={event => setQuery(event.target.value)}/></label><p>{filtered.length} concepts</p><ul className="names-catalogue">{filtered.map(entity => <li key={entity.id}><button aria-current={selected === entity.id ? 'true' : undefined} onClick={() => {setSelected(entity.id); setNotice(null);}}><b>{entity.label}</b><small>{entity.names.filter(name => !name.generated_from_name_id && name.text !== entity.label).map(name => name.text).join(', ') || 'No other authored names'}</small></button></li>)}</ul></aside>
      {selected ? <NamesConcept id={selected} entities={catalogue.entities} canWrite={catalogue.can_write} allowedActions={catalogue.allowed_actions} refresh={refresh} onChanged={changed}/> : <p>Select a concept to inspect its names and examples.</p>}
      </div>
    </>}
  </main>;
}
