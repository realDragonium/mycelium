// Revisioned AI texts: the per-action prompts (doctrine) and the
// documentation writing profiles (guidance, disclosure rules, templates).
import { useCallback, useState, type FormEvent } from 'react';
import { Card, LoadError, Loading, Notice, formatDate } from './lib';
import { HttpError, deleteJSON, enc, errorMessage, getJSON, postJSON, putJSON } from './api';
import { useAsync } from './use-async';
import { AudienceIdentity, type AudiencesResponse, type AudienceView } from './audiences';

// Saves are guarded by revision; a 409 keeps the edits and asks for a reload.
function saveMessage(e: unknown): string {
  if (e instanceof HttpError && e.status === 409) return 'This text changed elsewhere. Your edits are still here; reload before saving again.';
  return errorMessage(e, 'Could not save. Check the names and text, then try again.');
}

/* ============================ version history ============================ */
interface Version { id: string; version: number; text: string; created_at: string; created_by: string | null; deleted: boolean }

function PromptHistory({ type, name, canRestore, onRestored, onBusyChange }: {
  type: string; name: string; canRestore: boolean; onRestored: (saved: Version) => void | Promise<void>; onBusyChange?: (busy: boolean) => void;
}) {
  const load = useCallback(() => getJSON<{ versions: Version[] }>(`/api/documentation/prompts/history?type=${enc(type)}&name=${enc(name)}`).then(r => r.versions), [type, name]);
  const { state, reload, update } = useAsync(load);
  const [picked, setPicked] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const versions = state.status === 'ready' ? state.data : null;
  const selected = versions?.find(v => v.version === picked) || versions?.[0];

  const restore = async () => {
    if (!versions || !selected) return;
    onBusyChange?.(true); setBusy(true); setError(null);
    try {
      const saved = await postJSON<Version>('/api/documentation/prompts/restore', { type, name, version: selected.version, revision: versions[0].version });
      update(list => [saved, ...list.filter(v => v.version !== saved.version)]);
      setPicked(saved.version);
      await onRestored(saved);
    } catch (e) { setError(saveMessage(e)); }
    finally { setBusy(false); onBusyChange?.(false); }
  };

  return (
    <div className="subcard" aria-label={`History of ${name}`}>
      <div className="row between"><h3>History · {name}</h3><button type="button" className="btn ghost xs" disabled={busy} onClick={reload}>Reload</button></div>
      {error && <Notice tone="error">{error}</Notice>}
      {state.status === 'loading' && <Loading what="history" />}
      {state.status === 'error' && <LoadError error={state.error} what="history" />}
      {versions && (versions.length === 0 ? <p className="muted">No saved versions.</p> : <>
        <label className="field"><span>Version</span>
          <select className="input" value={selected?.version ?? ''} disabled={busy} onChange={e => setPicked(Number(e.target.value))}>
            {versions.map(v => <option key={v.id} value={v.version}>Version {v.version} · {formatDate(v.created_at)} · {v.created_by || 'unknown author'}{v.deleted ? ' · retired' : ''}</option>)}
          </select>
        </label>
        <pre className="code tall">{selected?.deleted ? 'This version retired the text.' : selected?.text}</pre>
        {canRestore && <button type="button" className="btn sm" disabled={busy || !selected || selected.deleted || selected.version === versions[0].version} onClick={() => void restore()}>{busy ? 'Restoring…' : 'Restore this version'}</button>}
        <p className="hint">A restored version becomes current; earlier versions stay available.</p>
      </>)}
    </div>
  );
}

/* ============================ prompts ============================ */
interface PromptAction { name: string; title: string; edited: boolean; newer_default_since: string | null }
interface Snapshot { version: number; text: string; source: string; note?: string | null }
interface Editor { current: Snapshot; default_text: string; newer_default_since: string | null; preview: string }

export function AIInstructions() {
  const list = useAsync(useCallback(() => getJSON<{ actions: PromptAction[]; can_write: boolean }>('/api/ai-instructions'), []));
  const [name, setName] = useState('ask');
  const [dirty, setDirty] = useState(false);

  // A reload after a save keeps the previous list so the open editor stays mounted.
  const listed = list.state.status === 'ready' ? list.state.data : list.state.previous;
  if (!listed && list.state.status === 'error') return <LoadError error={list.state.error} what="prompts" onRetry={list.reload} />;
  if (!listed) return <Loading what="prompts" />;
  const { actions, can_write } = listed;
  const drifted = actions.filter(a => a.newer_default_since);
  const choose = (next: string) => { if (next !== name && (!dirty || window.confirm('Discard unsaved instruction changes?'))) { setName(next); setDirty(false); } };

  return <>
    <p className="muted">Both providers use the same instructions. Saves keep a version history and apply to new runs; tool schemas, response formats and safeguards stay in code. A prompt nobody has edited follows each release; an edited one stays as you left it.</p>
    {drifted.length > 0 && <Notice tone="warn">{drifted.length === 1 ? 'One edited prompt is' : `${drifted.length} edited prompts are`} behind the default this release ships: {drifted.map(a => a.title).join(', ')}.</Notice>}
    <div className="split">
      <nav className="sub-list" aria-label="AI actions">
        {actions.map(a => (
          <button key={a.name} className={`sub-item${a.name === name ? ' on' : ''}`} aria-current={a.name === name} onClick={() => choose(a.name)}>
            <span>{a.title}</span>
            {a.edited && <span className="tag">edited</span>}
            {a.newer_default_since && <span className="tag warn">new default</span>}
          </button>
        ))}
      </nav>
      <PromptEditor key={name} name={name} title={actions.find(a => a.name === name)?.title || name} canWrite={can_write}
        onDirty={setDirty} onSaved={list.reload} />
    </div>
  </>;
}

function PromptEditor({ name, title, canWrite, onDirty, onSaved }: { name: string; title: string; canWrite: boolean; onDirty: (dirty: boolean) => void; onSaved: () => void }) {
  const { state, reload } = useAsync(useCallback(() => getJSON<Editor>(`/api/ai-instructions/${enc(name)}`), [name]));
  if (state.status === 'loading') return <Loading what="instructions" />;
  if (state.status === 'error') return <LoadError error={state.error} what="instructions" onRetry={reload} />;
  return <PromptForm key={state.data.current.version} editor={state.data} name={name} title={title} canWrite={canWrite} onDirty={onDirty}
    onSaved={() => { onSaved(); reload(); }} onReload={reload} />;
}

function PromptForm({ editor, name, title, canWrite, onDirty, onSaved, onReload }: {
  editor: Editor; name: string; title: string; canWrite: boolean; onDirty: (d: boolean) => void; onSaved: () => void; onReload: () => void;
}) {
  const head = editor.current;
  const [text, setText] = useState(head.text);
  const [preview, setPreview] = useState<string | null>(editor.preview);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [history, setHistory] = useState(false);
  const [compare, setCompare] = useState(false);
  const dirty = text !== head.text;
  const edit = (value: string) => { setText(value); setPreview(null); setMessage(null); onDirty(value !== head.text); };

  const save = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError(null); setMessage(null);
    try {
      await putJSON<unknown>('/api/documentation/prompts', { type: 'doctrine', name, text, revision: head.version });
      onDirty(false); onSaved();
    } catch (ex) { setError(saveMessage(ex)); }
    finally { setBusy(false); }
  };
  const inspect = async () => {
    setBusy(true); setError(null);
    try { setPreview((await postJSON<{ preview: string }>(`/api/ai-instructions/${enc(name)}/preview`, { text })).preview); }
    catch (ex) { setError(errorMessage(ex)); }
    finally { setBusy(false); }
  };
  const reload = () => { if (!dirty || window.confirm('Discard unsaved instruction changes?')) { onDirty(false); onReload(); } };

  return (
    <Card title={title} actions={<button type="button" className="btn ghost sm" disabled={busy} onClick={reload}>Reload</button>}>
      <p className="muted small">{head.source === 'saved' ? `Edited · saved version ${head.version}` : 'Shipped default'}{dirty ? ' · unsaved changes' : ''}</p>
      {head.note && <Notice tone="warn">{head.note}</Notice>}
      {editor.newer_default_since && (
        <Notice tone="warn">
          <div className="stack-sm">
            <div><b>The shipped default changed after this prompt was edited.</b> A newer default arrived with the release installed {formatDate(editor.newer_default_since)}; this instance keeps running your edited text until you choose.</div>
            <div className="row gap-sm">
              <button type="button" className="btn sm" onClick={() => setCompare(c => !c)}>{compare ? 'Hide the new default' : 'Compare with the new default'}</button>
              {canWrite && <button type="button" className="btn sm" disabled={busy || text === editor.default_text}
                onClick={() => { if (!dirty || window.confirm('Replace unsaved changes with the shipped default?')) edit(editor.default_text); }}>Load the new default into the editor</button>}
            </div>
          </div>
        </Notice>
      )}
      {compare && <div className="compare"><div><div className="col-head">Yours (current)</div><pre className="code tall">{head.text}</pre></div><div><div className="col-head">Shipped default</div><pre className="code tall">{editor.default_text}</pre></div></div>}
      {error && <Notice tone="error">{error}</Notice>}
      {message && <Notice tone="success">{message}</Notice>}
      <form onSubmit={save} className="stack-sm">
        <label className="field"><span>Behavioural instructions</span>
          <textarea className="input code-input" rows={16} value={text} readOnly={!canWrite} disabled={busy} required onChange={e => edit(e.target.value)} />
        </label>
        <div className="row gap-sm wrap">
          {canWrite && <>
            <button type="submit" className="btn primary" disabled={busy || !dirty || !text.trim()}>Save instructions</button>
            <button type="button" className="btn" disabled={busy || text === editor.default_text}
              onClick={() => { if (!dirty || window.confirm('Replace unsaved changes with the shipped default?')) edit(editor.default_text); }}>Use shipped default</button>
          </>}
          <button type="button" className="btn ghost" disabled={busy} onClick={() => void inspect()}>Preview combined prompt</button>
          <button type="button" className="btn ghost" onClick={() => setHistory(h => !h)}>{history ? 'Hide history' : 'Version history'}</button>
        </div>
      </form>
      <p className="hint">Using the shipped default fills the editor; save to apply it. {(name === 'docgen' || name === 'document_review') && 'Documentation profiles supply writing guidance, disclosure rules and templates; the preview marks where the selected profile goes. '}The preview shows the system instructions only: request text, evidence, tools and loop messages are added during a run.</p>
      {preview !== null && <details className="disclosure"><summary>Combined prompt preview</summary><pre className="code tall">{preview}</pre></details>}
      {history && <>
        {dirty && <p className="hint">Save or reload your edits before restoring a version.</p>}
        <PromptHistory type="doctrine" name={name} canRestore={canWrite && !dirty && !busy} onBusyChange={setBusy} onRestored={() => { setMessage('Version restored. New runs use it.'); onSaved(); }} />
      </>}
    </Card>
  );
}

/* ============================ documentation profiles ============================ */
interface Template { name: string; text: string; isNew?: boolean }
type Maintenance = 'manual' | 'propose' | 'auto-revise';
const MAINTENANCE: Record<Maintenance, string> = {
  manual: 'Manual: someone notices and revises',
  propose: 'Propose: add an update item to the plan',
  'auto-revise': 'Auto-revise: revise, review and publish by itself',
};
type Planning = 'off' | 'propose' | 'write';
const PLANNING: Record<Planning, string> = {
  off: 'Off: someone plans from Documents → Plan',
  propose: 'Propose: plan by itself; items wait for approval',
  write: 'Write: plan by itself and start the runs',
};
type PlanReview = 'person' | 'ai';
const PLAN_REVIEW: Record<PlanReview, string> = {
  person: 'A person approves or dismisses each item',
  ai: 'An AI reviewer approves or dismisses each item, with a reason',
};
type Recovery = 'person' | 'ai';
type Delivery = 'people' | 'agents' | 'auto';
interface Profile {
  name: string; revision: string | number; guidance: string; exposure: string; templates: Template[];
  audience: string | null; effective_audience: string | null; maintenance: Maintenance; planning: Planning;
  plan_review: PlanReview; recovery: Recovery; delivery: Delivery; delivery_destination: string;
  retired?: boolean; ready?: boolean; issues?: string[]; retired_templates?: string[];
}
interface Profiles { profiles: Profile[]; default_profile: string | null; can_write: boolean; can_retire: boolean }
interface ProfilesView extends Profiles { audiences: AudienceView[]; destinations: { name: string }[] }
interface SaveProfile { revision: string | number; guidance: string; exposure: string; templates: { name: string; text: string }[]; audience: string | null; maintenance: Maintenance; planning: Planning; plan_review: PlanReview; recovery: Recovery; delivery: Delivery; delivery_destination: string }

export function DocumentationProfiles() {
  const { state, reload } = useAsync(useCallback(async (signal: AbortSignal): Promise<ProfilesView> => {
    const [profiles, audiences, destinations] = await Promise.all([getJSON<Profiles>('/api/documentation/profiles', signal), getJSON<AudiencesResponse>('/api/audiences', signal), getJSON<{ destinations: { name: string }[] }>('/api/documentation/destinations', signal)]);
    return { ...profiles, audiences: audiences.audiences, destinations: destinations.destinations };
  }, []));
  const [form, setForm] = useState<Profile | null>(null);
  const [original, setOriginal] = useState<Profile | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<string | null>(null);
  const [showRetired, setShowRetired] = useState(false);
  const dirty = !!form && JSON.stringify(form) !== JSON.stringify(original);
  const data = state.status === 'ready' ? state.data : null;
  const defaultAudience = data?.audiences.find(audience => audience.default);
  const effectiveAudienceId = form && data
    ? !creating && form.audience === original?.audience ? form.effective_audience : form.audience ?? defaultAudience?.id ?? null
    : null;

  const discardOk = (q = 'Discard unsaved profile changes?') => !dirty || window.confirm(q);
  const open = (profile: Profile, isNew: boolean) => { setForm(profile); setOriginal(isNew ? null : profile); setCreating(isNew); setHistory(null); setError(null); setMessage(null); };
  const choose = (p: Profile) => { if (discardOk()) open(p, false); };
  const create = (source: Profile | null) => {
    if (!discardOk()) return;
    const audience = source?.audience && data?.audiences.some(item => !item.retired && item.id === source.audience) ? source.audience : null;
    open({ name: source ? `${source.name}-copy` : '', revision: '', guidance: source?.guidance || '', exposure: source?.exposure || '', templates: source ? source.templates.map(t => ({ ...t, isNew: true })) : [], audience, effective_audience: source?.effective_audience ?? null, maintenance: source?.maintenance ?? 'manual', planning: source?.planning ?? 'off', plan_review: source?.plan_review ?? 'person', recovery: source?.recovery ?? 'person', delivery: source?.delivery ?? 'people', delivery_destination: source?.delivery_destination ?? '' }, true);
  };
  const change = (patch: Partial<Profile>) => { setForm(f => f && { ...f, ...patch }); setMessage(null); };
  const changeTemplate = (i: number, patch: Partial<Template>) => form && change({ templates: form.templates.map((t, j) => j === i ? { ...t, ...patch } : t) });
  const duplicateTemplate = (t: Template) => form && change({ templates: [...form.templates, { name: uniqueName(form.templates, `${t.name}-copy`), text: t.text, isNew: true }] });

  const act = async (work: () => Promise<Profile>, done: string) => {
    setBusy(true); setError(null);
    try { const value = await work(); setForm(value); setOriginal(value); setCreating(false); reload(); setMessage(done); }
    catch (e) { setError(saveMessage(e)); }
    finally { setBusy(false); }
  };
  const path = (n: string) => `/api/documentation/profiles/${enc(n)}`;
  const save = (e: FormEvent) => {
    e.preventDefault();
    if (form) {
      const body: SaveProfile = { revision: form.revision, guidance: form.guidance, exposure: form.exposure, templates: form.templates.map(({ name, text }) => ({ name, text })), audience: form.audience, maintenance: form.maintenance, planning: form.planning, plan_review: form.plan_review, recovery: form.recovery, delivery: form.delivery, delivery_destination: form.delivery_destination };
      void act(() => putJSON<Profile>(path(form.name), body), 'Profile saved. New runs use it.');
    }
  };
  const retire = () => { if (form && window.confirm(`Retire ${form.name}? Its history and generated documents remain.`)) void act(() => deleteJSON<Profile>(path(form.name), { revision: form.revision }), 'Profile retired.'); };
  const reloadProfile = () => { if (form && !creating && discardOk('Discard local edits and load the saved profile?')) void act(() => getJSON<Profile>(path(form.name)), 'Saved profile loaded.'); };

  return (
    <Card title="Writing profiles & templates" actions={data?.can_write && <button type="button" className="btn sm" disabled={busy} onClick={() => create(null)}>New profile</button>}>
      <p className="muted">Writing guidance, disclosure rules and document templates used when generating documents. Stored here, versioned, no deploy needed. Audience guidance does not change who can open a generated document.</p>
      {error && <Notice tone="error">{error}</Notice>}
      {message && <Notice tone="success">{message}</Notice>}
      {state.status === 'loading' && <Loading what="profiles" />}
      {state.status === 'error' && <LoadError error={state.error} what="profiles" onRetry={reload} />}
      {data && <>
        <div className="row gap-sm wrap">
          {data.profiles.filter(p => showRetired || !p.retired).map(p => (
            <button key={p.name} type="button" className={`fchip${form?.name === p.name && !creating ? ' on' : ''}`} disabled={busy} onClick={() => choose(p)}>
              {p.name}{p.name === data.default_profile && ' · default'}{p.effective_audience ? ` · ${data.audiences.find(a => a.id === p.effective_audience)?.name || p.effective_audience}` : ' · audience unavailable'}{p.retired ? ' · retired' : p.ready === false ? ' · incomplete' : ''}
            </button>
          ))}
          <label className="check small"><input type="checkbox" checked={showRetired} onChange={e => setShowRetired(e.target.checked)} />Show retired</label>
        </div>
        {data.profiles.length === 0 && <p className="muted">No profiles yet. Create one and add a template to start.</p>}
        {form && (
          <div className="subcard">
            {!creating && <h3>{form.name}{form.retired && ' (retired)'}</h3>}
            {!creating && form.issues?.map(i => <Notice key={i} tone="warn">{i}</Notice>)}
            <form onSubmit={save}><fieldset disabled={busy || !data.can_write} className="stack">
              {creating && <label className="field"><span>Profile name</span><input className="input" value={form.name} required maxLength={200} pattern="[^/]+" placeholder="For example internal-doc" onChange={e => change({ name: e.target.value })} /></label>}
              <label className="field"><span>Audience</span><select className="input" value={form.audience || ''} disabled={!creating && !data.can_retire} onChange={e => change({ audience: e.target.value || null })}>
                <option value="">Default ({defaultAudience?.name || 'unavailable'})</option>
                {form.audience && !data.audiences.some(a => !a.retired && a.id === form.audience) && <option value={form.audience}>{data.audiences.find(a => a.id === form.audience)?.name || form.audience} (retired)</option>}
                {data.audiences.filter(a => !a.retired).map(a => <option key={a.id} value={a.id}>{a.name} · {a.scope}</option>)}
              </select>{!creating && !data.can_retire && <span className="hint">Only administrators can change an existing profile's audience.</span>}</label>
              <p className="hint">Effective audience: {effectiveAudienceId ? (() => { const audience = data.audiences.find(a => a.id === effectiveAudienceId); return audience ? <AudienceIdentity audience={audience} /> : effectiveAudienceId; })() : 'Unavailable'}</p>
              <label className="field"><span>When a cited statement changes</span><select className="input" value={form.maintenance} onChange={e => change({ maintenance: e.target.value as Maintenance })}>
                {(Object.keys(MAINTENANCE) as Maintenance[]).map(policy => <option key={policy} value={policy}>{MAINTENANCE[policy]}</option>)}
              </select><span className="hint">Auto-revise waits for the quiet period and daily limit under Settings → Limits. A published document gets its pull request updated, or a new one; a person still merges it.</span></label>
              <label className="field"><span>When statements are not in any document</span><select className="input" value={form.planning} onChange={e => change({ planning: e.target.value as Planning })}>
                {(Object.keys(PLANNING) as Planning[]).map(policy => <option key={policy} value={policy}>{PLANNING[policy]}</option>)}
              </select><span className="hint">Plans once the re-plan threshold under Settings → Limits is reached by statements no plan was offered. Write starts runs within the batch and active-run limits; each passes the usual document review.</span></label>
              <label className="field"><span>Who decides proposed plan items</span><select className="input" value={form.plan_review} onChange={e => change({ plan_review: e.target.value as PlanReview })}>
                {(Object.keys(PLAN_REVIEW) as PlanReview[]).map(policy => <option key={policy} value={policy}>{PLAN_REVIEW[policy]}</option>)}
              </select><span className="hint">The AI reviewer is never the planner: a model call separate from the planner's, or another agent while documentation planning is set to External agent. It also decides out-of-date documents. Approved items start within the batch and active-run limits; dismissals are remembered.</span></label>
              <label className="field"><span>When AI work fails</span><select className="input" value={form.recovery} onChange={e => change({ recovery: e.target.value as Recovery })}>
                <option value="person">Leave it for a person</option><option value="ai">Retry automatically, then give up with a reason</option>
              </select><span className="hint">Retries failed plans, plan reviews, items that could not start, runs the review refused (briefed with its notes) and publications, up to each kind's retries under Settings → Limits.</span></label>
              <label className="field"><span>Who delivers documents</span><select className="input" value={form.delivery} onChange={e => change({ delivery: e.target.value as Delivery })}>
                <option value="people">People publish from the document</option><option value="agents">Agents may also deliver over MCP (deliver_document)</option><option value="auto">Deliver automatically after review, and agents may deliver</option>
              </select><span className="hint">Automatic delivery opens or updates the pull request for every revision that passes review, of new documents too. Merging stays with the repository.</span></label>
              {form.delivery === 'auto' && <label className="field"><span>Repository for documents not published before</span><select className="input" value={form.delivery_destination} onChange={e => change({ delivery_destination: e.target.value })}>
                <option value="">None: only update documents published before</option>
                {form.delivery_destination && !data.destinations.some(destination => destination.name === form.delivery_destination) && <option value={form.delivery_destination}>{form.delivery_destination} (not configured)</option>}
                {data.destinations.map(destination => <option key={destination.name} value={destination.name}>{destination.name}</option>)}
              </select></label>}
              <label className="field"><span>Writing guidance</span><textarea className="input" rows={8} value={form.guidance} onChange={e => change({ guidance: e.target.value })} /></label>
              <label className="field"><span>Disclosure rules</span><textarea className="input" rows={6} value={form.exposure} placeholder="What may be disclosed, and what must stay internal." onChange={e => change({ exposure: e.target.value })} /></label>
              <h4 className="section-label">Document templates</h4>
              {form.templates.length === 0 && <p className="hint">Add a template to make this profile available for generation.</p>}
              {form.templates.map((t, i) => (
                <div key={i} className="subcard">
                  <label className="field"><span>Template name</span><input className="input" value={t.name} required maxLength={200} pattern="[^/]+" disabled={!creating && !t.isNew} onChange={e => changeTemplate(i, { name: e.target.value })} /></label>
                  <label className="field"><span>Template text</span><textarea className="input" rows={10} value={t.text} required onChange={e => changeTemplate(i, { text: e.target.value })} /></label>
                  <div className="row gap-sm wrap">
                    {!creating && !t.isNew && <button type="button" className="btn ghost xs" onClick={() => setHistory(t.name)}>History</button>}
                    <button type="button" className="btn ghost xs" onClick={() => duplicateTemplate(t)}>Duplicate</button>
                    {(data.can_retire || creating || t.isNew) && <button type="button" className="btn ghost xs" onClick={() => change({ templates: form.templates.filter((_, j) => j !== i) })}>Remove</button>}
                  </div>
                </div>
              ))}
              <div className="row gap-sm wrap">
                <button type="button" className="btn sm" onClick={() => change({ templates: [...form.templates, { name: '', text: '', isNew: true }] })}>Add template</button>
                <button type="submit" className="btn primary sm">{busy ? 'Saving…' : 'Save profile'}</button>
              </div>
            </fieldset></form>
            <div className="row gap-sm wrap">
              {!creating && <button type="button" className="btn ghost xs" disabled={busy} onClick={reloadProfile}>Reload saved profile</button>}
              {data.can_write && <button type="button" className="btn ghost xs" disabled={busy} onClick={() => create(form)}>Duplicate profile</button>}
              {data.can_retire && !creating && !form.retired && <button type="button" className="btn ghost xs" disabled={busy || form.name === data.default_profile} onClick={retire}>Retire profile</button>}
            </div>
            {form.name === data.default_profile && <p className="hint">This is the default profile. Choose another default under Documentation delivery before retiring it or its last template.</p>}
            {!data.can_write && <p className="hint">Writers can edit profiles; administrators can retire them.</p>}
            {!creating && original && (
              <label className="field"><span>Text history</span>
                <select className="input" disabled={busy} value={history || ''} onChange={e => setHistory(e.target.value || null)}>
                  <option value="">Choose text to inspect</option><option value="guidance">Writing guidance</option><option value="exposure">Disclosure rules</option>
                  {original.templates.map(t => <option key={t.name} value={t.name}>{t.name}</option>)}
                  {original.retired_templates?.map(n => <option key={n} value={n}>{n} (retired)</option>)}
                </select>
              </label>
            )}
            {history && !creating && <>
              {dirty && <p className="hint">Save or reload your edits before restoring history.</p>}
              <PromptHistory key={`${form.name}/${history}`} type="guideline-set" name={`${form.name}/${history}`} canRestore={data.can_write && !dirty && !busy} onBusyChange={setBusy} onRestored={reloadProfile} />
            </>}
          </div>
        )}
      </>}
    </Card>
  );
}

function uniqueName(templates: Template[], base: string): string {
  const names = new Set(templates.map(t => t.name));
  let name = base, n = 2;
  while (names.has(name)) name = `${base}-${n++}`;
  return name;
}
