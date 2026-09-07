function AliasSuggestions({ canWrite, onChanged }) {
  const [entries, setEntries] = React.useState([]);
  const [status, setStatus] = React.useState('pending');
  const [query, setQuery] = React.useState('');
  const [matches, setMatches] = React.useState([]);
  const [selected, setSelected] = React.useState([]);
  const [targets, setTargets] = React.useState({});
  const [concepts, setConcepts] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [notice, setNotice] = React.useState(null);
  const field = { width: '100%', minWidth: 0, padding: 8, boxSizing: 'border-box', background: 'var(--surface-2, var(--paper))', color: 'var(--ink)', border: '1px solid var(--rule, var(--line))', borderRadius: 4 };
  const request = async (url, options) => {
    const response = await fetch(url, options);
    const value = await response.json();
    if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'The alias request could not be completed.');
    return value;
  };
  const reload = React.useCallback(async () => {
    const value = await request(`/api/alias-suggestions?status=${status}`);
    setEntries(value.suggestions);
  }, [status]);
  React.useEffect(() => { let cancelled = false; setError(null); request(`/api/alias-suggestions?status=${status}`).then(value => { if (!cancelled) setEntries(value.suggestions); }).catch(e => { if (!cancelled) setError(e.message); }); return () => { cancelled = true; }; }, [status]);
  const act = async operation => {
    setBusy(true); setError(null); setNotice(null);
    try { await operation(); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const search = event => {
    event.preventDefault();
    act(async () => {
      const value = await request('/grep-statements', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query, limit: 30, match_aliased_mentions: false }) });
      setMatches(value.statements || []);
    });
  };
  const scan = () => act(async () => {
    const value = await request('/api/alias-suggestions/scan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ statement_ids: selected.map(item => item.id) }) });
    setNotice(value.suggestions.length ? `${value.suggestions.length} alias suggestion${value.suggestions.length === 1 ? '' : 's'} created for human review.` : 'No supported new aliases were found in the selected statements.');
    setStatus('pending');
    const pending = await request('/api/alias-suggestions?status=pending'); setEntries(pending.suggestions);
  });
  const review = (entry, action) => act(async () => {
    await request(`/api/alias-suggestions/${entry.draft_id}/${entry.operation_ref}/review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, expected_revision: entry.revision, ...(action === 'retarget' ? { entity_id: targets[entry.operation_ref] } : {}) }) });
    await reload();
    if (onChanged) onChanged();
    setNotice(action === 'accept' ? 'Alias accepted. Existing statements will be rediscovered using this name.' : action === 'reject' ? 'Suggestion rejected; its evidence remains in the history.' : 'Suggestion updated. Inspect its current target before accepting.');
  });
  const loadConcepts = () => act(async () => {
    const value = await request('/api/names-workspace');
    setConcepts(value.entities);
  });
  return <section aria-label="Alias suggestions" style={{ color: 'var(--ink)', overflowWrap: 'anywhere' }}>
    <p>AI suggests names that may identify an existing concept. A human writer must accept each suggestion, even when automatic draft review is enabled. Acceptance adds only this alias.</p>
    {error && <p role="alert">{error} <button disabled={busy} onClick={() => act(reload)}>Reload suggestions</button></p>}
    {notice && <p role="status">{notice}</p>}
    {canWrite && <details><summary>Discover aliases in existing statements</summary>
      <p>Select up to 50 statements. Discovery uses the independent Alias discovery model configured in AI settings.</p>
      <form onSubmit={search} style={{ display: 'flex', gap: 8 }}><input style={field} aria-label="Find statements for alias discovery" value={query} onChange={event => setQuery(event.target.value)} required /><button disabled={busy}>Search statements</button></form>
      <ul style={{ paddingLeft: 20 }}>{matches.map(item => <li key={item.id}><label><input type="checkbox" checked={selected.some(chosen => chosen.id === item.id)} disabled={busy || (selected.length >= 50 && !selected.some(chosen => chosen.id === item.id))} onChange={event => setSelected(current => event.target.checked ? [...current, { id: item.id, text: item.text }] : current.filter(chosen => chosen.id !== item.id))} /> {item.text}</label></li>)}</ul>
      {selected.length > 0 && <><p>{selected.length} statement{selected.length === 1 ? '' : 's'} selected across searches.</p><ul>{selected.map(item => <li key={item.id}>{item.text} <button disabled={busy} onClick={() => setSelected(current => current.filter(chosen => chosen.id !== item.id))}>Remove selection</button></li>)}</ul></>}
      <button disabled={busy || !selected.length} onClick={scan}>{busy ? 'Working…' : 'Discover alias suggestions'}</button>
    </details>}
    <label style={{ display: 'block', margin: '20px 0' }}>Show <select aria-label="Alias suggestion status" disabled={busy} value={status} onChange={event => setStatus(event.target.value)}><option value="pending">Needs human review</option><option value="accepted">Accepted</option><option value="rejected">Rejected</option><option value="all">All suggestions</option></select></label>
    {!entries.length && <p>No {status === 'all' ? '' : status} alias suggestions.</p>}
    {entries.map(entry => {
      const suggestion = entry.suggestion;
      const proposal = suggestion.proposal;
      const actionable = canWrite && suggestion.status === 'pending' && ['open', 'submitted'].includes(entry.draft_status);
      return <article key={entry.operation_ref} style={{ padding: 16, marginBottom: 16, border: '1px solid var(--rule, var(--line))', borderRadius: 6 }}>
        <h3 style={{ marginTop: 0 }}>“{proposal.alias}” → {entry.current_names.join(' / ') || proposal.entity_id}</h3>
        <p>{suggestion.status === 'pending' ? 'Needs human review' : suggestion.status} · <a href={`/cockpit/#/draft/${entry.draft_id}`}>{entry.draft_title || entry.draft_id}</a> · Draft {entry.draft_status}</p>
        <blockquote>{suggestion.evidence.quote}</blockquote>
        {suggestion.evidence.text !== suggestion.evidence.quote && <details><summary>Read source context</summary><p style={{ whiteSpace: 'pre-wrap' }}>{suggestion.evidence.text}</p></details>}
        {suggestion.evidence.statement_id && <p>Source statement: {suggestion.evidence.statement_id}</p>}
        <p>{proposal.reason}</p>
        {suggestion.original_proposal.entity_id !== proposal.entity_id && <p>The AI originally suggested concept {suggestion.original_proposal.entity_id}. A human changed the target; the source evidence and original recommendation remain recorded.</p>}
        {proposal.ambiguity && <p><strong>Possible ambiguity:</strong> {proposal.ambiguity}</p>}
        {suggestion.model && <p>Suggested by {suggestion.provider} · {suggestion.model} · Reasoning {suggestion.reasoning_effort || 'model default'}</p>}
        {entry.examples.length > 0 && <details><summary>Statements using this name</summary><ul>{entry.examples.map(item => <li key={item.statement_id}>{item.text}</li>)}</ul></details>}
        {entry.acceptance_committed && suggestion.status === 'pending' && <p>The alias was accepted but its draft decision was interrupted. Recover the recorded decision; this will not recreate a subsequently removed name.</p>}
        {entry.stale && !entry.acceptance_committed && suggestion.status === 'pending' && <p>Names or supporting evidence changed since this suggestion was prepared. Inspect the current names and source before refreshing. Changed source statements require a new scan.</p>}
        {actionable && <fieldset disabled={busy} style={{ border: 0, padding: 0, marginTop: 12 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}><button onClick={() => review(entry, 'accept')} disabled={entry.stale && !entry.acceptance_committed}>{entry.acceptance_committed ? 'Recover accepted decision' : 'Accept alias'}</button><button onClick={() => review(entry, 'reject')}>Reject suggestion</button>{entry.stale && !entry.acceptance_committed && <button onClick={() => review(entry, 'refresh')}>Refresh after inspection</button>}</div>
          <details style={{ marginTop: 12 }}><summary onClick={() => { if (!concepts.length) loadConcepts(); }}>Assign to a different concept</summary><label>Target concept<select aria-label={`Target concept for ${proposal.alias}`} style={field} value={targets[entry.operation_ref] || ''} onChange={event => setTargets(current => ({ ...current, [entry.operation_ref]: event.target.value }))}><option value="">Choose a concept</option>{concepts.map(item => <option key={item.id} value={item.id}>{item.label || item.names.map(name => name.text).join(' / ') || item.id}</option>)}</select></label><button disabled={!targets[entry.operation_ref]} onClick={() => review(entry, 'retarget')}>Change target for review</button></details>
        </fieldset>}
        {!!suggestion.history.length && <details><summary>Decision history</summary><ul>{suggestion.history.map((item, index) => <li key={index}>{item.action} · {item.actor_id} · {item.at} · {item.entity_id}</li>)}</ul></details>}
      </article>;
    })}
  </section>;
}
window.AliasSuggestions = AliasSuggestions;
