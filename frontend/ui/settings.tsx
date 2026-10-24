// Settings: everything an operator configures, grouped by what they are
// trying to do. Each section is its own route (#/settings/<section>).
import { useCallback, useState, type FormEvent, type ReactNode } from 'react';
import { ActionModels, DraftReviewSettings } from './ai-settings';
import { AIUsage } from './ai-usage';
import { AIInstructions, DocumentationProfiles } from './documentation-profiles';
import { ProductSettings } from './product-settings';
import { SetupSection } from './setup';
import { AudiencesSettings, type AudiencesResponse } from './audiences';
import { Card, I, LoadError, Loading, Notice, PageHeader, useMe } from './lib';
import { Link, type SettingsSection } from './router';
import { deleteJSON, enc, errorMessage, getJSON, patchJSON, postJSON, type Me, type Role } from './api';
import { PREF_CHOICES, usePrefs, type Prefs } from './prefs';
import { useAsync } from './use-async';

const ROLES: Role[] = ['reader', 'drafter', 'writer', 'admin'];

interface SectionDef { id: SettingsSection; label: string; blurb: string }
const GROUPS: { title: string; sections: SectionDef[] }[] = [
  { title: 'You', sections: [
    { id: 'account', label: 'Account & tokens', blurb: 'Who you are signed in as, and the MCP tokens your clients use.' },
    { id: 'appearance', label: 'Appearance', blurb: 'Theme and density for this browser.' },
  ] },
  { title: 'Instance', sections: [
    { id: 'setup', label: 'Set up Mycelium', blurb: 'What this instance still needs before its AI work runs, each step linking to where it is done.' },
  ] },
  { title: 'People', sections: [
    { id: 'members', label: 'Members & invites', blurb: 'Who can use this instance, with which role, plus service accounts for agents.' },
  ] },
  { title: 'AI', sections: [
    { id: 'models', label: 'Models', blurb: 'Which provider and model each AI action uses.' },
    { id: 'prompts', label: 'Prompts', blurb: 'The behavioural instructions each AI action follows.' },
    { id: 'review', label: 'Draft review', blurb: 'Whether submitted drafts get an automatic AI review, and whether it may apply them.' },
    { id: 'limits', label: 'Limits', blurb: 'Token, time and concurrency budgets for each AI action.' },
    { id: 'usage', label: 'AI usage', blurb: 'Tokens each AI action and model used, and an optional monthly token budget.' },
  ] },
  { title: 'Publishing', sections: [
    { id: 'documentation', label: 'Documentation', blurb: 'Writing profiles and templates, and the GitHub repositories documents publish to.' },
    { id: 'audiences', label: 'Audiences', blurb: 'Who documentation is written for, and which statements each audience may see.' },
  ] },
];
const SECTIONS = GROUPS.flatMap(g => g.sections);

export function SettingsScreen({ section }: { section: SettingsSection }) {
  const me = useMe();
  const audienceLoad = useCallback((signal: AbortSignal) => me?.role === 'admin'
    ? getJSON<AudiencesResponse>('/api/audiences', signal).then(response => response.audiences.filter(audience => !audience.retired))
    : Promise.resolve([]), [me]);
  const audiences = useAsync(audienceLoad).state;
  const waiting = audiences.status === 'ready' ? audiences.data.reduce((total, audience) => total + audience.pending_statements, 0) : 0;
  const def = SECTIONS.find(s => s.id === section) || SECTIONS[0];
  return (
    <main className="page settings-page">
      <PageHeader eyebrow="Settings" title={def.label} blurb={def.blurb} />
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Settings sections">
          {GROUPS.map(g => (
            <div key={g.title} className="sn-group">
              <div className="sn-title">{g.title}</div>
              {g.sections.map(s => <Link key={s.id} to={{ view: 'settings', section: s.id }} className={`sn-link${s.id === def.id ? ' on' : ''}`}>{s.label}{s.id === 'audiences' && waiting > 0 && <span className="sn-count" aria-label={`${waiting} grants waiting for confirmation`}>{waiting}</span>}</Link>)}
            </div>
          ))}
        </nav>
        <div className="settings-body"><Section id={def.id} /></div>
      </div>
    </main>
  );
}

function Section({ id }: { id: SettingsSection }) {
  switch (id) {
    case 'account': return <><AccountCard /><TokensCard /></>;
    case 'appearance': return <AppearanceCard />;
    case 'setup': return <SetupSection />;
    case 'members': return <MembersSection />;
    case 'models': return <ActionModels />;
    case 'prompts': return <AIInstructions />;
    case 'review': return <DraftReviewSettings />;
    case 'limits': return <ProductSettings kinds={['ask', 'ingest', 'docgen', 'draft_review', 'alias_discovery', 'audience_labelling', 'documentation_planning', 'documentation_maintenance', 'connect', 'concurrency', 'media']} />;
    case 'documentation': return <><ProductSettings kinds={['documentation']} /><DocumentationProfiles /></>;
    case 'usage': return <AIUsage />;
    case 'audiences': return <AudiencesSettings />;
  }
}

/* ---------------- shared bits ---------------- */
export const RoleBadge = ({ role }: { role: string }) => <span className={`role-badge ${role}`}>{role}</span>;

function Secret({ label, value, onDismiss }: { label: ReactNode; value: string; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="notice success secret">
      <div className="stack-sm grow">
        <div>{label}</div>
        <code className="secret-value">{value}</code>
        <div className="row gap-sm">
          <button className="btn sm" onClick={() => { void navigator.clipboard?.writeText(value); setCopied(true); }}>{copied ? 'Copied' : 'Copy'}</button>
          <button className="btn ghost sm" onClick={onDismiss}>Dismiss</button>
        </div>
      </div>
    </div>
  );
}

/* ---------------- account ---------------- */
function AccountCard() {
  const me = useMe();
  if (!me) return <Card title="Account"><Loading what="your account" /></Card>;
  return (
    <Card title="Account">
      <dl className="kv-grid">
        <dt>Name</dt><dd>{me.name}</dd>
        <dt>Role</dt><dd><RoleBadge role={me.role} /></dd>
        <dt>Type</dt><dd>{me.type}</dd>
        <dt>Authentication</dt>
        <dd>{me.auth_enabled ? <span className="ok-text">enabled</span> : <span className="warn-text">disabled: everyone is the local admin</span>}</dd>
      </dl>
    </Card>
  );
}

interface Token {
  id: string; name: string; prefix: string; scope: Role; created_at: string; last_used_at: string | null; revoked_at: string | null;
  oauth: boolean;
}
type CreatedToken = Token & { token: string };

const scopesFor = (role: Role): Role[] => ROLES.slice(0, ROLES.indexOf(role) + 1);

function TokensCard() {
  const me = useMe();
  const { state, reload } = useAsync(useCallback(() => getJSON<{ tokens: Token[] }>('/api/me/tokens').then(r => r.tokens), []));
  const [name, setName] = useState('');
  const [scope, setScope] = useState<Role>('writer');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedToken | null>(null);
  const scopes = me ? scopesFor(me.role) : ['reader' as Role];

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true); setErr(null);
    try {
      setCreated(await postJSON<CreatedToken>('/api/me/tokens', { name: name.trim(), scope: scopes.includes(scope) ? scope : scopes[scopes.length - 1] }));
      setName(''); reload();
    } catch (ex) { setErr(errorMessage(ex)); }
    finally { setBusy(false); }
  };
  const revoke = async (id: string) => {
    if (!window.confirm('Revoke this token? Any MCP client using it loses access.')) return;
    try { await deleteJSON<unknown>(`/api/me/tokens/${enc(id)}`); reload(); }
    catch (ex) { setErr(errorMessage(ex)); }
  };

  return (
    <Card title="MCP tokens" actions={<a className="btn ghost sm" href="/connect"><I.plug width="14" height="14" />How to connect a client</a>}>
      <p className="muted">Bearer tokens for MCP clients such as Claude Desktop, Claude Code and CI agents, sent as <code>Authorization: Bearer myc_…</code>. Each token is revocable on its own; the secret is shown once, at creation.</p>
      {created && <Secret label={<>Token <b>{created.name}</b> created. Copy it now: it will not be shown again.</>} value={created.token} onDismiss={() => setCreated(null)} />}
      {err && <Notice tone="error">{err}</Notice>}
      {state.status === 'loading' && <Loading what="tokens" />}
      {state.status === 'error' && <LoadError error={state.error} what="tokens" onRetry={reload} />}
      {state.status === 'ready' && (state.data.length === 0
        ? <p className="muted">No tokens yet. Create one below to connect an MCP client.</p>
        : <table className="tbl compact">
          <thead><tr><th>Name</th><th>Identifier</th><th>Scope</th><th>Created</th><th>Last used</th><th /></tr></thead>
          <tbody>{state.data.map(t => (
            <tr key={t.id} className={t.revoked_at ? 'revoked' : ''}>
              <td>{t.name}{t.revoked_at && <span className="muted small"> · revoked</span>}</td>
              <td className="mono">myc_{t.prefix}_…</td>
              <td><RoleBadge role={t.scope} /></td>
              <td className="muted">{t.created_at.slice(0, 10)}</td>
              <td className="muted">{t.last_used_at ? t.last_used_at.slice(0, 10) : '—'}</td>
              <td className="num">{!t.revoked_at && <button className="btn ghost xs" onClick={() => void revoke(t.id)}>Revoke</button>}</td>
            </tr>
          ))}</tbody>
        </table>)}
      <form className="inline-form" onSubmit={create}>
        <input className="input grow" placeholder="Token name, for example laptop" aria-label="Token name" value={name} onChange={e => setName(e.target.value)} required maxLength={80} />
        <select className="input" aria-label="Token scope" value={scopes.includes(scope) ? scope : scopes[scopes.length - 1]} onChange={e => setScope(e.target.value as Role)}>
          {scopes.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <button className="btn primary" type="submit" disabled={busy || !name.trim()}>{busy ? 'Creating…' : 'Create token'}</button>
      </form>
    </Card>
  );
}

/* ---------------- appearance ---------------- */
const PREF_LABELS: { [K in keyof Prefs]: { label: string; hint: string } } = {
  theme: { label: 'Theme', hint: '' },
  density: { label: 'Density', hint: 'Spacing in lists and tables.' },
  answerVoice: { label: 'Answer typeface', hint: 'Ask answers in a serif reading face, or in the interface face.' },
};

function AppearanceCard() {
  const { prefs, setPref } = usePrefs();
  const row = <K extends keyof Prefs>(key: K) => (
    <div className="field-row" key={key}>
      <div><div className="field-label">{PREF_LABELS[key].label}</div>{PREF_LABELS[key].hint && <div className="hint">{PREF_LABELS[key].hint}</div>}</div>
      <div className="seg" role="group" aria-label={PREF_LABELS[key].label}>
        {(PREF_CHOICES[key] as readonly Prefs[K][]).map(v => <button key={v} className={prefs[key] === v ? 'on' : ''} aria-pressed={prefs[key] === v} onClick={() => setPref(key, v)}>{v}</button>)}
      </div>
    </div>
  );
  return <Card title="Appearance"><p className="muted">Saved in this browser only.</p>{row('theme')}{row('density')}{row('answerVoice')}</Card>;
}

/* ---------------- members ---------------- */
interface User { id: string; name: string; email: string | null; type: string; role: Role; status: string; blocked_by_domain_policy: boolean }
interface Invite { id: string; email: string; role: Role; created_at: string; link: string }

function MembersSection() {
  const me = useMe();
  if (!me) return <Loading what="your account" />;
  if (me.role !== 'admin') return <Notice>Only administrators manage members. You are signed in as a {me.role}.</Notice>;
  if (!me.auth_enabled) {
    return <Notice>User management is off while authentication is disabled: everyone is the local admin. Set <code>MYCELIUM_AUTH=on</code> to invite people. A reviewer service account can still be created under <Link to={{ view: 'settings', section: 'review' }}>Draft review</Link>.</Notice>;
  }
  return <MembersCard me={me} />;
}

function MembersCard({ me }: { me: Me }) {
  const load = useCallback(() => Promise.all([
    getJSON<{ users: User[] }>('/api/admin/users').then(r => r.users),
    getJSON<{ invites: Invite[] }>('/api/admin/invites').then(r => r.invites),
  ]), []);
  const { state, reload } = useAsync(load);
  const [err, setErr] = useState<string | null>(null);
  const [svcName, setSvcName] = useState('');
  const [svcRole, setSvcRole] = useState<Role>('writer');
  const [invEmail, setInvEmail] = useState('');
  const [invRole, setInvRole] = useState<Role>('writer');
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [svcToken, setSvcToken] = useState<{ name: string; token: string } | null>(null);

  const act = async (action: () => Promise<unknown>) => {
    setErr(null);
    try { await action(); reload(); } catch (e) { setErr(errorMessage(e)); }
  };
  const createService = (e: FormEvent) => { e.preventDefault(); void act(async () => { await postJSON('/api/admin/users', { name: svcName.trim(), role: svcRole, type: 'service' }); setSvcName(''); }); };
  const invite = (e: FormEvent) => { e.preventDefault(); void act(async () => { const r = await postJSON<{ link: string }>('/api/admin/invites', { email: invEmail.trim(), role: invRole }); setInviteLink(r.link); setInvEmail(''); }); };
  const mint = (userId: string) => {
    const name = window.prompt('Token name, for example ci-agent:');
    if (name) void act(async () => setSvcToken(await postJSON<{ name: string; token: string }>(`/api/admin/users/${enc(userId)}/tokens`, { name, scope: 'writer' })));
  };
  const roleSelect = (value: Role, onChange: (r: Role) => void, label: string) => (
    <select className="input" aria-label={label} value={value} onChange={e => onChange(e.target.value as Role)}>{ROLES.map(r => <option key={r} value={r}>{r}</option>)}</select>
  );

  return (
    <>
      {err && <Notice tone="error">{err}</Notice>}
      {svcToken && <Secret label={<>Token <b>{svcToken.name}</b> for the service account. Copy it now.</>} value={svcToken.token} onDismiss={() => setSvcToken(null)} />}
      {inviteLink && <Secret label="Invite link: send it to the recipient." value={inviteLink} onDismiss={() => setInviteLink(null)} />}
      <Card title="Members">
        <p className="muted">People sign in through your identity provider after accepting an invite. Service accounts are token-only identities for agents.</p>
        {state.status === 'loading' && <Loading what="members" />}
        {state.status === 'error' && <LoadError error={state.error} what="members" onRetry={reload} />}
        {state.status === 'ready' && (
          <table className="tbl compact">
            <thead><tr><th>Name</th><th>Email</th><th>Type</th><th>Role</th><th>Status</th><th /></tr></thead>
            <tbody>{state.data[0].map(u => (
              <tr key={u.id} className={u.status === 'active' ? '' : 'revoked'}>
                <td>{u.name}{u.id === me.id && <span className="muted small"> · you</span>}</td>
                <td className="muted">{u.email || '—'}</td>
                <td>{u.type}</td>
                <td>{roleSelect(u.role, r => void act(() => patchJSON(`/api/admin/users/${enc(u.id)}`, { role: r })), `Role of ${u.name}`)}</td>
                <td>
                  {u.status}
                  {u.blocked_by_domain_policy && <div><span className="tag warn" title="This email domain is not in MYCELIUM_ALLOWED_EMAIL_DOMAINS, so the user cannot sign in or use tokens.">blocked by domain policy</span></div>}
                </td>
                <td><div className="row gap-sm end">
                  {u.type === 'service' && <button className="btn ghost xs" onClick={() => mint(u.id)}>Mint token</button>}
                  <button className="btn ghost xs" onClick={() => void act(() => patchJSON(`/api/admin/users/${enc(u.id)}`, { status: u.status === 'active' ? 'suspended' : 'active' }))}>
                    {u.status === 'active' ? 'Suspend' : 'Activate'}
                  </button>
                </div></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Card>
      <Card title="Pending invites">
        {state.status === 'ready' && (state.data[1].length === 0 ? <p className="muted">No pending invites.</p> : (
          <table className="tbl compact">
            <thead><tr><th>Email</th><th>Role</th><th>Created</th><th /></tr></thead>
            <tbody>{state.data[1].map(i => (
              <tr key={i.id}>
                <td>{i.email}</td><td><RoleBadge role={i.role} /></td><td className="muted">{i.created_at.slice(0, 10)}</td>
                <td className="num row gap-sm end">
                  <button className="btn ghost xs" onClick={() => void navigator.clipboard?.writeText(i.link)}>Copy link</button>
                  <button className="btn ghost xs" onClick={() => { if (window.confirm('Revoke this invite?')) void act(() => deleteJSON(`/api/admin/invites/${enc(i.id)}`)); }}>Revoke</button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        ))}
        <div className="two-col">
          <form className="stack-sm" onSubmit={invite}>
            <div className="field-label">Invite a person</div>
            <div className="row gap-sm">
              <input className="input grow" type="email" placeholder="email@example.com" aria-label="Invitee email" value={invEmail} onChange={e => setInvEmail(e.target.value)} />
              {roleSelect(invRole, setInvRole, 'Invitee role')}
              <button className="btn primary" type="submit" disabled={!invEmail.trim()}>Invite</button>
            </div>
          </form>
          <form className="stack-sm" onSubmit={createService}>
            <div className="field-label">Create a service account</div>
            <div className="row gap-sm">
              <input className="input grow" placeholder="Name, for example ci-agent" aria-label="Service account name" maxLength={80} value={svcName} onChange={e => setSvcName(e.target.value)} />
              {roleSelect(svcRole, setSvcRole, 'Service account role')}
              <button className="btn" type="submit" disabled={!svcName.trim()}>Create</button>
            </div>
          </form>
        </div>
      </Card>
    </>
  );
}
