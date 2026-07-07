// Settings screen — account info, MCP token management, and (when the
// current user is an admin) user / invite management.
//
// Tokens: the raw secret is only shown once at creation. After that the
// UI only knows the prefix and metadata. Revoking is a soft delete:
// the row stays so the user can see what was revoked and when.

const { useState: useSt, useEffect: useESt, useCallback: useCBSt } = React;

async function _fetchJSON(url, init) {
  const r = await fetch(url, init);
  if (!r.ok) {
    let detail;
    try { detail = (await r.json()).detail; } catch (_) { detail = r.statusText; }
    throw new Error(detail || `${init && init.method || 'GET'} ${url} → ${r.status}`);
  }
  return r.json();
}

function _postJSON(url, body) {
  return _fetchJSON(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(body),
  });
}

function _del(url) {
  return _fetchJSON(url, { method: 'DELETE' });
}

function _patchJSON(url, body) {
  return _fetchJSON(url, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(body),
  });
}

// ---------- account header ----------

function AccountCard({ me }) {
  return (
    <section className="card" style={{ padding: '20px 24px', marginBottom: 24 }}>
      <h2 style={{ margin: 0, fontSize: 14, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--ink-3)' }}>Account</h2>
      <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: '120px 1fr', rowGap: 6, columnGap: 16, fontSize: 13 }}>
        <span style={{ color: 'var(--ink-3)' }}>Name</span><span>{me.name}</span>
        <span style={{ color: 'var(--ink-3)' }}>Role</span><span><RoleBadge role={me.role} /></span>
        <span style={{ color: 'var(--ink-3)' }}>Type</span><span>{me.type}</span>
        <span style={{ color: 'var(--ink-3)' }}>Auth</span>
        <span>
          {me.auth_enabled
            ? <span style={{ color: 'var(--green, #16a34a)' }}>enabled</span>
            : <span style={{ color: 'var(--amber, #d97706)' }}>disabled — running as local admin</span>}
        </span>
      </div>
    </section>
  );
}

function RoleBadge({ role }) {
  const colors = {
    admin: { bg: 'rgba(220,38,38,0.12)', fg: '#dc2626' },
    writer: { bg: 'rgba(37,99,235,0.12)', fg: '#2563eb' },
    drafter: { bg: 'rgba(217,119,6,0.12)', fg: '#d97706' },
    reader: { bg: 'rgba(107,114,128,0.18)', fg: 'var(--ink-2)' },
  };
  const c = colors[role] || colors.reader;
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 4,
      fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 600,
      background: c.bg, color: c.fg,
    }}>{role}</span>
  );
}

// ---------- tokens ----------

function TokensCard({ me }) {
  const [tokens, setTokens] = useSt([]);
  const [loading, setLoading] = useSt(true);
  const [err, setErr] = useSt(null);
  const [creating, setCreating] = useSt(false);
  const [newName, setNewName] = useSt('');
  const [newScope, setNewScope] = useSt('writer');
  const [justCreated, setJustCreated] = useSt(null);

  const reload = useCBSt(async () => {
    setLoading(true); setErr(null);
    try {
      const data = await _fetchJSON('/api/me/tokens');
      setTokens(data.tokens || []);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, []);

  useESt(() => { reload(); }, [reload]);

  const onCreate = async (e) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true); setErr(null);
    try {
      const { token, ...meta } = await _postJSON('/api/me/tokens', { name: newName.trim(), scope: newScope });
      setJustCreated({ token, ...meta });
      setNewName('');
      await reload();
    } catch (e) { setErr(e.message); }
    finally { setCreating(false); }
  };

  const onRevoke = async (id) => {
    if (!confirm('Revoke this token? Any MCP client using it will lose access.')) return;
    try { await _del(`/api/me/tokens/${id}`); await reload(); }
    catch (e) { setErr(e.message); }
  };

  const scopes = me.role === 'admin'
    ? ['reader', 'drafter', 'writer', 'admin']
    : me.role === 'writer'
      ? ['reader', 'drafter', 'writer']
      : me.role === 'drafter'
        ? ['reader', 'drafter']
        : ['reader'];

  return (
    <section className="card" style={{ padding: '20px 24px', marginBottom: 24 }}>
      <h2 style={{ margin: 0, fontSize: 14, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--ink-3)' }}>MCP tokens</h2>
      <p style={{ marginTop: 8, marginBottom: 18, fontSize: 12.5, color: 'var(--ink-3)' }}>
        Bearer tokens for MCP clients (Claude Desktop, Claude Code, CI agents). Pass as <code>Authorization: Bearer myc_…</code>. Each token is independently revocable; the secret is shown only once at creation.
        {' '}<a href="/connect" style={{ color: 'var(--accent, #2563eb)' }}>How do I connect a client? →</a>
      </p>

      {justCreated && (
        <div style={{ background: 'rgba(22,163,74,0.08)', border: '1px solid rgba(22,163,74,0.35)', borderRadius: 6, padding: '12px 14px', marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: 'var(--ink-2)', marginBottom: 6 }}>
            Token <strong>{justCreated.name}</strong> created. Copy it now — it will not be shown again.
          </div>
          <code style={{ display: 'block', padding: '8px 10px', background: 'var(--surface-2)', borderRadius: 4, fontSize: 12, wordBreak: 'break-all', userSelect: 'all' }}>
            {justCreated.token}
          </code>
          <button
            onClick={() => { navigator.clipboard.writeText(justCreated.token); }}
            style={{ marginTop: 8, fontSize: 11, padding: '4px 10px' }}
          >Copy</button>
          <button
            onClick={() => setJustCreated(null)}
            style={{ marginTop: 8, marginLeft: 6, fontSize: 11, padding: '4px 10px' }}
          >Dismiss</button>
        </div>
      )}

      {err && <div style={{ color: 'var(--red, #dc2626)', fontSize: 12.5, marginBottom: 12 }}>{err}</div>}

      {loading ? (
        <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>loading…</div>
      ) : tokens.length === 0 ? (
        <div style={{ fontSize: 12.5, color: 'var(--ink-3)', fontStyle: 'italic' }}>No tokens yet. Create one below to connect an MCP client.</div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--rule)', textAlign: 'left', color: 'var(--ink-3)' }}>
              <th style={{ padding: '6px 8px' }}>Name</th>
              <th style={{ padding: '6px 8px' }}>Identifier</th>
              <th style={{ padding: '6px 8px' }}>Scope</th>
              <th style={{ padding: '6px 8px' }}>Created</th>
              <th style={{ padding: '6px 8px' }}>Last used</th>
              <th style={{ padding: '6px 8px' }}></th>
            </tr>
          </thead>
          <tbody>
            {tokens.map(t => (
              <tr key={t.id} style={{ borderBottom: '1px solid var(--rule)', opacity: t.revoked_at ? 0.45 : 1 }}>
                <td style={{ padding: '8px' }}>{t.name}{t.revoked_at && <span style={{ marginLeft: 6, fontSize: 10.5, color: 'var(--ink-3)' }}>revoked</span>}</td>
                <td style={{ padding: '8px', fontFamily: 'var(--mono)', fontSize: 11.5 }}>myc_{t.prefix}_…</td>
                <td style={{ padding: '8px' }}><RoleBadge role={t.scope} /></td>
                <td style={{ padding: '8px', color: 'var(--ink-3)' }}>{(t.created_at || '').slice(0, 10)}</td>
                <td style={{ padding: '8px', color: 'var(--ink-3)' }}>{t.last_used_at ? t.last_used_at.slice(0, 10) : '—'}</td>
                <td style={{ padding: '8px', textAlign: 'right' }}>
                  {!t.revoked_at && <button onClick={() => onRevoke(t.id)} style={{ fontSize: 11, padding: '3px 8px' }}>Revoke</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <form onSubmit={onCreate} style={{ marginTop: 20, display: 'flex', gap: 8, alignItems: 'center', borderTop: '1px solid var(--rule)', paddingTop: 16 }}>
        <input
          type="text" placeholder="Token name (e.g. laptop)" value={newName}
          onChange={(e) => setNewName(e.target.value)} required maxLength={80}
          style={{ flex: 1, padding: '6px 10px', fontSize: 13 }}
        />
        <select value={newScope} onChange={(e) => setNewScope(e.target.value)} style={{ padding: '6px 10px', fontSize: 13 }}>
          {scopes.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <button type="submit" disabled={creating || !newName.trim()} style={{ padding: '6px 14px', fontSize: 13 }}>
          {creating ? 'Creating…' : 'Create token'}
        </button>
      </form>
    </section>
  );
}

// ---------- admin: users ----------

function UsersCard() {
  const [users, setUsers] = useSt([]);
  const [invites, setInvites] = useSt([]);
  const [err, setErr] = useSt(null);
  const [loading, setLoading] = useSt(true);
  const [newSvcName, setNewSvcName] = useSt('');
  const [newSvcRole, setNewSvcRole] = useSt('writer');
  const [newInvEmail, setNewInvEmail] = useSt('');
  const [newInvRole, setNewInvRole] = useSt('writer');
  const [lastInviteLink, setLastInviteLink] = useSt(null);
  const [svcTokenJustCreated, setSvcTokenJustCreated] = useSt(null);

  const reload = useCBSt(async () => {
    setLoading(true); setErr(null);
    try {
      const [u, i] = await Promise.all([
        _fetchJSON('/api/admin/users'),
        _fetchJSON('/api/admin/invites'),
      ]);
      setUsers(u.users || []);
      setInvites(i.invites || []);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, []);

  useESt(() => { reload(); }, [reload]);

  const onCreateService = async (e) => {
    e.preventDefault();
    if (!newSvcName.trim()) return;
    setErr(null);
    try {
      await _postJSON('/api/admin/users', { name: newSvcName.trim(), role: newSvcRole, type: 'service' });
      setNewSvcName('');
      await reload();
    } catch (e) { setErr(e.message); }
  };

  const onCreateInvite = async (e) => {
    e.preventDefault();
    if (!newInvEmail.trim()) return;
    setErr(null);
    try {
      const r = await _postJSON('/api/admin/invites', { email: newInvEmail.trim(), role: newInvRole });
      setLastInviteLink(r.link);
      setNewInvEmail('');
      await reload();
    } catch (e) { setErr(e.message); }
  };

  const onChangeRole = async (userId, role) => {
    try { await _patchJSON(`/api/admin/users/${userId}`, { role }); await reload(); }
    catch (e) { setErr(e.message); }
  };

  const onToggleStatus = async (u) => {
    const next = u.status === 'active' ? 'suspended' : 'active';
    try { await _patchJSON(`/api/admin/users/${u.id}`, { status: next }); await reload(); }
    catch (e) { setErr(e.message); }
  };

  const onMintForService = async (userId) => {
    const name = prompt('Token name (e.g. ci-agent):');
    if (!name) return;
    try {
      const r = await _postJSON(`/api/admin/users/${userId}/tokens`, { name, scope: 'writer' });
      setSvcTokenJustCreated({ user_id: userId, ...r });
    } catch (e) { setErr(e.message); }
  };

  const onRevokeInvite = async (id) => {
    if (!confirm('Revoke this invite?')) return;
    try { await _del(`/api/admin/invites/${id}`); await reload(); }
    catch (e) { setErr(e.message); }
  };

  return (
    <section className="card" style={{ padding: '20px 24px', marginBottom: 24 }}>
      <h2 style={{ margin: 0, fontSize: 14, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--ink-3)' }}>Users & invites</h2>
      <p style={{ marginTop: 8, marginBottom: 18, fontSize: 12.5, color: 'var(--ink-3)' }}>
        Admin-only. Humans authenticate via OIDC after accepting an invite; service accounts are token-only identities for third-party agents.
      </p>

      {err && <div style={{ color: 'var(--red, #dc2626)', fontSize: 12.5, marginBottom: 12 }}>{err}</div>}

      {svcTokenJustCreated && (
        <div style={{ background: 'rgba(22,163,74,0.08)', border: '1px solid rgba(22,163,74,0.35)', borderRadius: 6, padding: '12px 14px', marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: 'var(--ink-2)', marginBottom: 6 }}>
            Token <strong>{svcTokenJustCreated.name}</strong> for service account created. Copy it now.
          </div>
          <code style={{ display: 'block', padding: '8px 10px', background: 'var(--surface-2)', borderRadius: 4, fontSize: 12, wordBreak: 'break-all', userSelect: 'all' }}>
            {svcTokenJustCreated.token}
          </code>
          <button onClick={() => setSvcTokenJustCreated(null)} style={{ marginTop: 8, fontSize: 11, padding: '4px 10px' }}>Dismiss</button>
        </div>
      )}

      {loading ? (
        <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>loading…</div>
      ) : (
        <>
          <h3 style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 4, marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.04em' }}>Members</h3>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5, marginBottom: 24 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--rule)', textAlign: 'left', color: 'var(--ink-3)' }}>
                <th style={{ padding: '6px 8px' }}>Name</th>
                <th style={{ padding: '6px 8px' }}>Email</th>
                <th style={{ padding: '6px 8px' }}>Type</th>
                <th style={{ padding: '6px 8px' }}>Role</th>
                <th style={{ padding: '6px 8px' }}>Status</th>
                <th style={{ padding: '6px 8px' }}></th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} style={{ borderBottom: '1px solid var(--rule)', opacity: u.status === 'active' ? 1 : 0.5 }}>
                  <td style={{ padding: '8px' }}>{u.name}</td>
                  <td style={{ padding: '8px', color: 'var(--ink-3)' }}>{u.email || '—'}</td>
                  <td style={{ padding: '8px' }}>{u.type}</td>
                  <td style={{ padding: '8px' }}>
                    <select value={u.role} onChange={(e) => onChangeRole(u.id, e.target.value)} style={{ fontSize: 12, padding: '2px 6px' }}>
                      <option value="reader">reader</option>
                      <option value="drafter">drafter</option>
                      <option value="writer">writer</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td style={{ padding: '8px' }}>{u.status}</td>
                  <td style={{ padding: '8px', textAlign: 'right' }}>
                    {u.type === 'service' && <button onClick={() => onMintForService(u.id)} style={{ fontSize: 11, padding: '3px 8px', marginRight: 4 }}>Mint token</button>}
                    <button onClick={() => onToggleStatus(u)} style={{ fontSize: 11, padding: '3px 8px' }}>
                      {u.status === 'active' ? 'Suspend' : 'Activate'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 4, marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.04em' }}>Pending invites</h3>
          {invites.length === 0 ? (
            <div style={{ fontSize: 12.5, color: 'var(--ink-3)', fontStyle: 'italic', marginBottom: 16 }}>No pending invites.</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5, marginBottom: 24 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--rule)', textAlign: 'left', color: 'var(--ink-3)' }}>
                  <th style={{ padding: '6px 8px' }}>Email</th>
                  <th style={{ padding: '6px 8px' }}>Role</th>
                  <th style={{ padding: '6px 8px' }}>Created</th>
                  <th style={{ padding: '6px 8px' }}>Link</th>
                  <th style={{ padding: '6px 8px' }}></th>
                </tr>
              </thead>
              <tbody>
                {invites.map(i => (
                  <tr key={i.id} style={{ borderBottom: '1px solid var(--rule)' }}>
                    <td style={{ padding: '8px' }}>{i.email}</td>
                    <td style={{ padding: '8px' }}><RoleBadge role={i.role} /></td>
                    <td style={{ padding: '8px', color: 'var(--ink-3)' }}>{(i.created_at || '').slice(0, 10)}</td>
                    <td style={{ padding: '8px' }}>
                      <button onClick={() => { navigator.clipboard.writeText(i.link); }} style={{ fontSize: 11, padding: '3px 8px' }}>Copy link</button>
                    </td>
                    <td style={{ padding: '8px', textAlign: 'right' }}>
                      <button onClick={() => onRevokeInvite(i.id)} style={{ fontSize: 11, padding: '3px 8px' }}>Revoke</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {lastInviteLink && (
            <div style={{ background: 'rgba(37,99,235,0.08)', border: '1px solid rgba(37,99,235,0.35)', borderRadius: 6, padding: '10px 12px', marginBottom: 16, fontSize: 12 }}>
              Invite link (send to the recipient):
              <code style={{ display: 'block', padding: '6px 8px', marginTop: 6, background: 'var(--surface-2)', borderRadius: 4, fontSize: 11.5, wordBreak: 'break-all', userSelect: 'all' }}>{lastInviteLink}</code>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <form onSubmit={onCreateService} style={{ borderTop: '1px solid var(--rule)', paddingTop: 14 }}>
              <h4 style={{ fontSize: 11.5, color: 'var(--ink-3)', margin: '0 0 8px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Create service account</h4>
              <div style={{ display: 'flex', gap: 6 }}>
                <input value={newSvcName} onChange={(e) => setNewSvcName(e.target.value)} placeholder="Name (e.g. ci-agent)" maxLength={80} style={{ flex: 1, padding: '6px 10px', fontSize: 13 }} />
                <select value={newSvcRole} onChange={(e) => setNewSvcRole(e.target.value)} style={{ padding: '6px 10px', fontSize: 13 }}>
                  <option value="reader">reader</option>
                  <option value="drafter">drafter</option>
                  <option value="writer">writer</option>
                  <option value="admin">admin</option>
                </select>
                <button type="submit" disabled={!newSvcName.trim()} style={{ padding: '6px 12px', fontSize: 13 }}>Create</button>
              </div>
            </form>

            <form onSubmit={onCreateInvite} style={{ borderTop: '1px solid var(--rule)', paddingTop: 14 }}>
              <h4 style={{ fontSize: 11.5, color: 'var(--ink-3)', margin: '0 0 8px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Invite human</h4>
              <div style={{ display: 'flex', gap: 6 }}>
                <input value={newInvEmail} onChange={(e) => setNewInvEmail(e.target.value)} placeholder="email@example.com" type="email" style={{ flex: 1, padding: '6px 10px', fontSize: 13 }} />
                <select value={newInvRole} onChange={(e) => setNewInvRole(e.target.value)} style={{ padding: '6px 10px', fontSize: 13 }}>
                  <option value="reader">reader</option>
                  <option value="drafter">drafter</option>
                  <option value="writer">writer</option>
                  <option value="admin">admin</option>
                </select>
                <button type="submit" disabled={!newInvEmail.trim()} style={{ padding: '6px 12px', fontSize: 13 }}>Invite</button>
              </div>
            </form>
          </div>
        </>
      )}
    </section>
  );
}

// ---------- screen root ----------

function SettingsScreen() {
  const [me, setMe] = useSt(null);
  const [err, setErr] = useSt(null);

  useESt(() => {
    _fetchJSON('/api/me').then(setMe).catch(e => setErr(e.message));
  }, []);

  if (err) return <main className="page"><div className="page-inner" style={{ padding: '32px 24px' }}><div style={{ color: 'var(--red, #dc2626)' }}>{err}</div></div></main>;
  if (!me) return <main className="page"><div className="page-inner" style={{ padding: '32px 24px', color: 'var(--ink-3)' }}>loading…</div></main>;

  return (
    <main className="page">
      <div className="page-inner" style={{ maxWidth: 960, padding: '32px 24px 80px' }}>
        <header style={{ marginBottom: 24 }}>
          <h1 style={{ margin: 0 }}>Settings</h1>
          <p style={{ marginTop: 6, color: 'var(--ink-3)', fontSize: 13 }}>Account, MCP tokens, and (if admin) user management.</p>
        </header>

        <AccountCard me={me} />
        <TokensCard me={me} />
        {me.role === 'admin' && me.auth_enabled && <UsersCard />}
        {me.role === 'admin' && !me.auth_enabled && (
          <div style={{ fontSize: 12.5, color: 'var(--ink-3)', fontStyle: 'italic', padding: '16px 0' }}>
            User management is hidden while auth is disabled — only the local-admin exists in this mode. Set <code>MYCELIUM_AUTH=on</code> to enable it.
          </div>
        )}
      </div>
    </main>
  );
}

window.SettingsScreen = SettingsScreen;
