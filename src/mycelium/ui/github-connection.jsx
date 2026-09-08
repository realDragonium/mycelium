/** @typedef {{name: string, owner: string, repo: string, enabled: boolean}} GitHubConnection */
/** @typedef {{installation_id: number, repository_id: number, owner: string, repo: string, default_branch: string}} GitHubRepository */

async function githubRequest(path, body) {
  const response = await fetch('/api/github' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'GitHub setup could not be completed. Try again.');
  return data;
}

function GitHubConnection({ canConfigure, onConnected, onConnections, destinationSaved }) {
  const [status, setStatus] = React.useState(null);
  const [repositories, setRepositories] = React.useState([]);
  const [selected, setSelected] = React.useState('');
  const [branch, setBranch] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [message, setMessage] = React.useState(null);
  const [refresh, setRefresh] = React.useState(0);
  React.useEffect(() => { if (destinationSaved) setMessage(null); }, [destinationSaved]);
  const returnState = new URLSearchParams(window.location.hash.split('?')[1] || '').get('github');
  React.useEffect(() => {
    let cancelled = false;
    setError(null);
    githubRequest('').then(async data => {
      if (cancelled) return;
      setStatus(data); onConnections(data.connections);
      if (data.selecting && canConfigure) {
        const repos = await githubRequest('/repositories');
        if (!cancelled) setRepositories(repos);
      }
    }).catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [refresh, canConfigure]);
  const key = repo => `${repo.installation_id}:${repo.repository_id}`;
  const repository = repositories.find(repo => key(repo) === selected);
  const run = async action => {
    setBusy(true); setError(null); setMessage(null);
    try { await action(); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const start = existing => run(async () => {
    const result = await githubRequest('/start', { existing, surface: window.location.pathname.startsWith('/cockpit') ? 'cockpit' : 'ui' });
    window.location.assign(result.url);
  });
  const connect = event => {
    event.preventDefault();
    if (!repository) return;
    run(async () => {
      const connection = await githubRequest('/connections', { installation_id: repository.installation_id, repository_id: repository.repository_id, base_branch: branch });
      onConnected(connection);
      setMessage('Repository connected. Save documentation delivery below to use it.');
      setRefresh(value => value + 1);
    });
  };
  const disconnect = connection => run(async () => {
    await githubRequest('/disconnect', { name: connection.name });
    setMessage(`${connection.owner}/${connection.repo} disconnected. Documents and existing pull requests are preserved.`);
    setRefresh(value => value + 1);
  });
  return <section aria-label="GitHub connection" style={{ marginTop: 18, padding: 16, border: '1px solid var(--rule, var(--line))', borderRadius: 6 }}>
    <h3 style={{ marginTop: 0, color: 'var(--ink)' }}>Connect a GitHub repository</h3>
    <p>Connect GitHub, select a repository, then save its branch and file path below. This lets writers in this Mycelium instance publish documentation pull requests.</p>
    {!status && !error && <p>Loading GitHub connection…</p>}
    {status?.message && <p role="status">{status.message}</p>}
    {status && !status.configured && <p>The server administrator needs to register a GitHub App and configure it once. See <a href="/ui/github-setup.html" target="_blank" rel="noreferrer">GitHub App setup</a>.</p>}
    {canConfigure ? <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      <button type="button" style={productSettingsStyle.button} disabled={busy || !status?.configured} onClick={() => start(false)}>Connect GitHub</button>
      <button type="button" style={productSettingsStyle.button} disabled={busy || !status?.configured} onClick={() => start(true)}>Use existing GitHub installation</button>
    </div> : <p>Only administrators can connect or disconnect repositories.</p>}
    {returnState === 'cancelled' && !message && <p>GitHub authorization was cancelled. You can connect again when ready.</p>}
    {returnState === 'pending' && !message && <p>GitHub may require organization approval. Once approved, choose Use existing GitHub installation.</p>}
    {status?.selecting && canConfigure && <form onSubmit={connect} style={{ marginTop: 16 }}>
      <fieldset disabled={busy} style={{ border: 0, padding: 0 }}>
        <div style={productSettingsStyle.grid}>
          <label style={productSettingsStyle.field}>GitHub repository<select required style={productSettingsStyle.input} value={selected} onChange={event => {
            setSelected(event.target.value);
            setBranch(repositories.find(repo => key(repo) === event.target.value)?.default_branch || '');
          }}><option value="">Select a repository</option>{repositories.map(repo => <option key={key(repo)} value={key(repo)}>{repo.owner}/{repo.repo}</option>)}</select></label>
          <label style={productSettingsStyle.field}>Base branch<input required style={productSettingsStyle.input} value={branch} onChange={event => setBranch(event.target.value)} maxLength={200} /></label>
        </div>
        <button type="submit" style={{ ...productSettingsStyle.button, marginTop: 12 }} disabled={!repository || !branch || busy}>{busy ? 'Connecting…' : 'Use repository'}</button>
      </fieldset>
      {!repositories.length && <p>No writable repositories are available. Check which repositories the App can access and whether your organization has approved the installation and its Contents and Pull requests permissions.</p>}
    </form>}
    {!!status?.connections.length && <ul>{status.connections.map(connection => <li key={connection.name} style={{ marginTop: 10 }}>
      <strong>{connection.owner}/{connection.repo}</strong> · {connection.enabled ? 'Connected' : 'Disconnected'}{' '}
      {canConfigure && connection.enabled && <button type="button" style={productSettingsStyle.button} disabled={busy} onClick={() => disconnect(connection)}>Disconnect</button>}
      {!connection.enabled && canConfigure && <span>Use existing GitHub installation to reconnect this repository.</span>}
    </li>)}</ul>}
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    <button type="button" style={{ ...productSettingsStyle.button, marginTop: 12 }} disabled={busy} onClick={() => setRefresh(value => value + 1)}>Refresh GitHub access</button>
  </section>;
}

Object.assign(window, { GitHubConnection });
