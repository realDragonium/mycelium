// Connect a GitHub repository through the GitHub App so writers can publish
// documentation pull requests. GitHub's install flow returns to
// #/documentation?tab=settings&github=…, which the router maps to
// Settings → Documentation with `github` kept in the hash.
import { useEffect, useState, type FormEvent } from 'react';
import { Notice } from './lib';
import { errorMessage, getJSON, postJSON } from './api';

export interface GitHubRepoConnection { name: string; owner: string; repo: string; enabled: boolean; base_branch?: string }
interface Repository { installation_id: number; repository_id: number; owner: string; repo: string; default_branch: string }
interface Status { configured: boolean; selecting: boolean; message?: string | null; connections: GitHubRepoConnection[] }

const FALLBACK = 'GitHub setup could not be completed. Try again.';
const github = <T,>(path: string, body?: unknown) => (body === undefined ? getJSON<T>('/api/github' + path) : postJSON<T>('/api/github' + path, body))
  .catch((e: unknown) => { throw new Error(errorMessage(e, FALLBACK)); });

export function GitHubConnection({ canConfigure, onConnected, onConnections }: {
  canConfigure: boolean; onConnected: (c: GitHubRepoConnection) => void; onConnections: (c: GitHubRepoConnection[]) => void;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [selected, setSelected] = useState('');
  const [branch, setBranch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const returnState = new URLSearchParams(window.location.hash.split('?')[1] || '').get('github');

  useEffect(() => {
    let cancelled = false;
    github<Status>('').then(async data => {
      if (cancelled) return;
      setStatus(data); setError(null); onConnections(data.connections);
      if (data.selecting && canConfigure) {
        const repos = await github<Repository[]>('/repositories');
        if (!cancelled) setRepositories(repos);
      }
    }).catch((e: unknown) => { if (!cancelled) setError(errorMessage(e)); });
    return () => { cancelled = true; };
  }, [refresh, canConfigure, onConnections]);

  const key = (r: Repository) => `${r.installation_id}:${r.repository_id}`;
  const repository = repositories.find(r => key(r) === selected);
  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError(null); setMessage(null);
    try { await action(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };
  const start = (existing: boolean) => run(async () => {
    const result = await github<{ url: string }>('/start', { existing, surface: 'ui' });
    window.location.assign(result.url);
  });
  const connect = (e: FormEvent) => {
    e.preventDefault();
    if (!repository) return;
    void run(async () => {
      onConnected(await github<GitHubRepoConnection>('/connections', { installation_id: repository.installation_id, repository_id: repository.repository_id, base_branch: branch }));
      setMessage('Repository connected. Save documentation delivery below to use it.');
      setRefresh(n => n + 1);
    });
  };
  const disconnect = (c: GitHubRepoConnection) => run(async () => {
    await github<unknown>('/disconnect', { name: c.name });
    setMessage(`${c.owner}/${c.repo} disconnected. Documents and existing pull requests are kept.`);
    setRefresh(n => n + 1);
  });

  return (
    <section className="subcard" aria-label="GitHub connection">
      <h3>Connect a GitHub repository</h3>
      <p className="hint">Connect GitHub, pick a repository, then save its branch and file path below. Writers on this instance can then publish documentation pull requests.</p>
      {!status && !error && <p className="muted small">Checking the GitHub connection…</p>}
      {status?.message && <Notice>{status.message}</Notice>}
      {status && !status.configured && <Notice tone="warn">The server administrator needs to register a GitHub App once. See <a href="/ui/github-setup.html" target="_blank" rel="noreferrer">GitHub App setup</a>.</Notice>}
      {canConfigure ? (
        <div className="row gap-sm">
          <button type="button" className="btn sm" disabled={busy || !status?.configured} onClick={() => void start(false)}>Connect GitHub</button>
          <button type="button" className="btn ghost sm" disabled={busy || !status?.configured} onClick={() => void start(true)}>Use an existing installation</button>
        </div>
      ) : <p className="hint">Only administrators can connect or disconnect repositories.</p>}
      {returnState === 'cancelled' && !message && <Notice>GitHub authorization was cancelled. Connect again when ready.</Notice>}
      {returnState === 'pending' && !message && <Notice>GitHub may need organization approval. Once approved, choose Use an existing installation.</Notice>}
      {status?.selecting && canConfigure && (
        <form onSubmit={connect}>
          <fieldset disabled={busy}>
            <div className="field-grid">
              <label className="field"><span>GitHub repository</span>
                <select className="input" required value={selected} onChange={e => { setSelected(e.target.value); setBranch(repositories.find(r => key(r) === e.target.value)?.default_branch || ''); }}>
                  <option value="">Select a repository</option>
                  {repositories.map(r => <option key={key(r)} value={key(r)}>{r.owner}/{r.repo}</option>)}
                </select>
              </label>
              <label className="field"><span>Base branch</span><input className="input" required value={branch} maxLength={200} onChange={e => setBranch(e.target.value)} /></label>
            </div>
            <button type="submit" className="btn primary sm" disabled={!repository || !branch || busy}>{busy ? 'Connecting…' : 'Use repository'}</button>
          </fieldset>
          {!repositories.length && <p className="hint">No writable repositories are available. Check which repositories the App can access, and whether your organization approved the installation with Contents and Pull requests permissions.</p>}
        </form>
      )}
      {!!status?.connections.length && (
        <ul className="plain-list">{status.connections.map(c => (
          <li key={c.name} className="row gap-sm">
            <b>{c.owner}/{c.repo}</b><span className={c.enabled ? 'ok-text' : 'warn-text'}>{c.enabled ? 'connected' : 'disconnected'}</span>
            {canConfigure && c.enabled && <button type="button" className="btn ghost xs" disabled={busy} onClick={() => void disconnect(c)}>Disconnect</button>}
            {canConfigure && !c.enabled && <span className="hint">Use an existing installation to reconnect.</span>}
          </li>
        ))}</ul>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      {message && <Notice tone="success">{message}</Notice>}
      <button type="button" className="btn ghost xs" disabled={busy} onClick={() => setRefresh(n => n + 1)}>Refresh GitHub access</button>
    </section>
  );
}
