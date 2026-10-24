import { useCallback, useRef, useState, type FormEvent } from 'react';
import { AudienceIdentity, type AudienceRef, type AudiencesResponse } from './audiences';
import {
  errorMessage, getJSON, media, type MediaAttachment, type MediaDetails, type MediaFilter,
  type MediaTargetKind, type MediaView,
} from './api';
import { Card, EmptyState, LoadError, Loading, Notice, PageHeader, formatDate, useMe } from './lib';
import { Link } from './router';
import { dataOf, useAsync } from './use-async';

const ACCEPT = 'image/png,image/jpeg,image/gif,image/webp,video/mp4,video/webm';
const FILTERS: { id: MediaFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'unattached', label: 'Unattached' },
  { id: 'no_alt_text', label: 'No alt text' },
  { id: 'unlabelled', label: 'Unlabelled' },
  { id: 'old', label: 'Old' },
];

interface DetailsDraft { alt_text: string; caption: string; source_url: string; product_version: string; captured_at: string }

const detailsOf = (item?: MediaView): DetailsDraft => ({
  alt_text: item?.alt_text || '',
  caption: item?.caption || '',
  source_url: item?.source_url || '',
  product_version: item?.product_version || '',
  captured_at: item?.captured_at?.slice(0, 10) || '',
});

const detailsBody = (draft: DetailsDraft): MediaDetails => ({
  alt_text: draft.alt_text.trim(),
  caption: draft.caption.trim(),
  source_url: draft.source_url.trim() || null,
  product_version: draft.product_version.trim() || null,
  captured_at: draft.captured_at || null,
});

const canEditMedia = (me: ReturnType<typeof useMe>) => !!me && (me.role === 'writer' || me.role === 'admin');

function DetailsFields({ value, onChange, file }: {
  value: DetailsDraft; onChange: (value: DetailsDraft) => void; file?: { required: boolean; onChange: (file: File | null) => void };
}) {
  const change = (key: keyof DetailsDraft, next: string) => onChange({ ...value, [key]: next });
  return <div className="field-grid">
    {file && <label className="field"><span>File</span><input className="input" type="file" accept={ACCEPT} required={file.required} onChange={event => file.onChange(event.target.files?.[0] || null)} /></label>}
    <label className="field"><span>Alt text</span><input className="input" required maxLength={1000} value={value.alt_text} onChange={event => change('alt_text', event.target.value)} /></label>
    <label className="field"><span>Caption</span><input className="input" maxLength={1000} value={value.caption} onChange={event => change('caption', event.target.value)} /></label>
    <label className="field"><span>Source URL</span><input className="input" type="url" maxLength={1000} value={value.source_url} onChange={event => change('source_url', event.target.value)} /></label>
    <label className="field"><span>Product version</span><input className="input" maxLength={100} value={value.product_version} onChange={event => change('product_version', event.target.value)} /></label>
    <label className="field"><span>Capture date</span><input className="input" type="date" value={value.captured_at} onChange={event => change('captured_at', event.target.value)} /></label>
  </div>;
}

function MediaPreview({ item, thumbnail = false }: { item: MediaView; thumbnail?: boolean }) {
  const className = `media-preview${thumbnail ? ' thumbnail' : ''}`;
  return item.content_type.startsWith('image/')
    ? <img className={className} src={item.url} alt={item.alt_text} loading="lazy" />
    : <video className={className} src={item.url} controls preload="metadata" aria-label={item.alt_text} />;
}

function AudienceLabel({ item, audiences }: { item: MediaView; audiences: AudienceRef[] }) {
  if (item.audiences === null) return <span className="media-unlabelled">Internal only (unlabelled)</span>;
  if (item.audiences.length === 0) return <span className="muted">No audiences</span>;
  return <span className="media-audiences">{item.audiences.map(id => {
    const audience = audiences.find(candidate => candidate.id === id);
    return audience ? <AudienceIdentity key={id} audience={audience} /> : <code key={id}>{id}</code>;
  })}</span>;
}

function DetailsEditor({ item, onSaved, onCancel }: { item: MediaView; onSaved: () => void; onCancel: () => void }) {
  const [draft, setDraft] = useState(() => detailsOf(item));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null);
    try { await media.update(item.id, detailsBody(draft)); onSaved(); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <form className="subcard" onSubmit={save}><fieldset disabled={busy}>
    <DetailsFields value={draft} onChange={setDraft} />
    {error && <Notice tone="error">{error}</Notice>}
    <div className="row gap-sm"><button className="btn primary sm" type="submit" disabled={!draft.alt_text.trim()}>{busy ? 'Saving…' : 'Save details'}</button><button className="btn ghost sm" type="button" onClick={onCancel}>Cancel</button></div>
  </fieldset></form>;
}

function ReplaceForm({ item, onSaved, onCancel }: { item: MediaView; onSaved: () => void; onCancel: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    setBusy(true); setError(null);
    try { await media.replace(item.id, file); onSaved(); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <form className="subcard" onSubmit={save}><fieldset disabled={busy}>
    <label className="field"><span>Replacement file</span><input className="input" type="file" accept={ACCEPT} required onChange={event => setFile(event.target.files?.[0] || null)} /></label>
    {error && <Notice tone="error">{error}</Notice>}
    <div className="row gap-sm"><button className="btn primary sm" type="submit" disabled={!file}>{busy ? 'Replacing…' : 'Replace file'}</button><button className="btn ghost sm" type="button" onClick={onCancel}>Cancel</button></div>
  </fieldset></form>;
}

function AudienceEditor({ item, audiences, onSaved, onCancel }: { item: MediaView; audiences: AudienceRef[]; onSaved: () => void; onCancel: () => void }) {
  const [selected, setSelected] = useState(() => new Set(item.audiences || []));
  const [unlabelled, setUnlabelled] = useState(item.audiences === null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toggle = (id: string) => setSelected(current => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null);
    try { await media.label(item.id, unlabelled ? null : [...selected]); onSaved(); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <form className="subcard audience-curation" onSubmit={save}><fieldset disabled={busy}>
    <label className="check"><input type="checkbox" checked={unlabelled} onChange={event => setUnlabelled(event.target.checked)} />Internal only (unlabelled)</label>
    <div className="audience-checks">{audiences.map(audience => <label key={audience.id} className="check"><input type="checkbox" disabled={unlabelled} checked={selected.has(audience.id)} onChange={() => toggle(audience.id)} /><AudienceIdentity audience={audience} /></label>)}</div>
    {error && <Notice tone="error">{error}</Notice>}
    <div className="row gap-sm"><button className="btn primary sm" type="submit">{busy ? 'Saving…' : 'Save audience label'}</button><button className="btn ghost sm" type="button" onClick={onCancel}>Cancel</button></div>
  </fieldset></form>;
}

function AttachForm({ item, onSaved, onCancel }: { item: MediaView; onSaved: () => void; onCancel: () => void }) {
  const [id, setId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const kind: MediaTargetKind | null = id.trim().startsWith('stm_') ? 'statement' : id.trim().startsWith('ent_') ? 'entity' : null;
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!kind) { setError('Enter a statement id starting stm_ or a concept id starting ent_.'); return; }
    setBusy(true); setError(null);
    try { await media.attach(item.id, { kind, id: id.trim() }); onSaved(); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <form className="inline-form" onSubmit={save}>
    <label className="field grow"><span>Statement or concept id</span><input className="input" value={id} placeholder="stm_… or ent_…" onChange={event => setId(event.target.value)} /></label>
    <button className="btn primary sm" type="submit" disabled={busy || !id.trim()}>{busy ? 'Attaching…' : 'Attach'}</button>
    <button className="btn ghost sm" type="button" onClick={onCancel}>Cancel</button>
    {error && <Notice tone="error">{error}</Notice>}
  </form>;
}

function Attachments({ item, editable, onDetach }: { item: MediaView; editable: boolean; onDetach: (target: MediaAttachment) => void }) {
  if (!item.attachments.length) return <span className="muted">Unattached</span>;
  return <span className="media-attachments">{item.attachments.map(target => <span key={`${target.kind}:${target.id}`}>
    <Link to={{ view: target.kind, id: target.id }}>{target.kind === 'entity' ? 'Concept' : 'Statement'} {target.id}</Link>
    {editable && <button className="link-btn" type="button" onClick={() => onDetach(target)}>detach</button>}
  </span>)}</span>;
}

function MediaItem({ item, audiences, editable, admin, library, panelTarget, onChanged }: {
  item: MediaView; audiences: AudienceRef[]; editable: boolean; admin: boolean; library: boolean; panelTarget?: MediaAttachment; onChanged: () => void;
}) {
  const [open, setOpen] = useState<'details' | 'replace' | 'audiences' | 'attach' | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const act = async (work: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await work(); onChanged(); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  const changed = () => { setOpen(null); onChanged(); };
  const remove = () => {
    if (window.confirm(`Delete ${item.id}? This cannot be undone.`)) void act(() => media.remove(item.id));
  };
  return <article className={`media-item${library ? ' library' : ''}`}>
    <div className="media-visual"><MediaPreview item={item} thumbnail={library} /></div>
    <div className="media-body">
      <div className="row between wrap"><code>{item.id}</code><span className="muted small">{item.origin} · {(item.byte_size / 1024).toFixed(0)} KB · v{item.content_version}</span></div>
      <p className={`media-alt${item.alt_text ? '' : ' missing'}`}>{item.alt_text || 'No alt text'}</p>
      {item.caption && <p className="media-caption">{item.caption}</p>}
      <dl className="media-meta">
        <dt>Audience</dt><dd><AudienceLabel item={item} audiences={audiences} /></dd>
        {item.source_url && <><dt>Source</dt><dd><a href={item.source_url} target="_blank" rel="noreferrer">{item.source_url}</a></dd></>}
        {item.product_version && <><dt>Version</dt><dd>{item.product_version}</dd></>}
        {item.captured_at && <><dt>Captured</dt><dd>{formatDate(item.captured_at)}</dd></>}
        {library && <><dt>Attached to</dt><dd><Attachments item={item} editable={editable && !busy} onDetach={target => void act(() => media.detach(item.id, target))} /></dd></>}
      </dl>
      {item.content_changed_at && <Notice tone="warn">Audience label needs confirming: the file changed {formatDate(item.content_changed_at)}.</Notice>}
      {item.stale.length > 0 && <Notice tone="warn"><span>Old media: {item.stale.join('; ')}.</span></Notice>}
      {error && <Notice tone="error">{error}</Notice>}
      {editable && <div className="media-actions row gap-sm wrap">
        <button className="btn ghost sm" type="button" disabled={busy} onClick={() => setOpen(open === 'details' ? null : 'details')}>Edit details</button>
        <button className="btn ghost sm" type="button" disabled={busy} onClick={() => setOpen(open === 'replace' ? null : 'replace')}>Replace file</button>
        <button className="btn ghost sm" type="button" disabled={busy} onClick={() => setOpen(open === 'audiences' ? null : 'audiences')}>Audience label</button>
        {item.content_changed_at && item.audiences !== null && <button className="btn sm" type="button" disabled={busy} onClick={() => void act(() => media.confirmLabel(item.id))}>Confirm label</button>}
        {library
          ? <button className="btn ghost sm" type="button" disabled={busy} onClick={() => setOpen(open === 'attach' ? null : 'attach')}>Attach to…</button>
          : panelTarget && <button className="btn ghost sm" type="button" disabled={busy} onClick={() => void act(() => media.detach(item.id, panelTarget))}>Detach</button>}
        {admin && <button className="btn danger sm" type="button" disabled={busy} onClick={remove}>Delete</button>}
      </div>}
      {open === 'details' && <DetailsEditor item={item} onSaved={changed} onCancel={() => setOpen(null)} />}
      {open === 'replace' && <ReplaceForm item={item} onSaved={changed} onCancel={() => setOpen(null)} />}
      {open === 'audiences' && <AudienceEditor item={item} audiences={audiences} onSaved={changed} onCancel={() => setOpen(null)} />}
      {open === 'attach' && <AttachForm item={item} onSaved={changed} onCancel={() => setOpen(null)} />}
    </div>
  </article>;
}

function UploadForm({ target, onUploaded }: { target?: MediaAttachment; onUploaded: () => void }) {
  const [draft, setDraft] = useState(detailsOf);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useRef<HTMLFormElement>(null);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    setBusy(true); setError(null);
    try {
      await media.upload(file, detailsBody(draft), target);
      setDraft(detailsOf()); setFile(null); form.current?.reset(); onUploaded();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <form ref={form} className="card media-upload" onSubmit={save}><fieldset disabled={busy}>
    <h2>Upload media</h2>
    <DetailsFields value={draft} onChange={setDraft} file={{ required: true, onChange: setFile }} />
    {error && <Notice tone="error">{error}</Notice>}
    <button className="btn primary" type="submit" disabled={!file || !draft.alt_text.trim()}>{busy ? 'Uploading…' : 'Upload'}</button>
  </fieldset></form>;
}

function useAudiences(enabled: boolean) {
  return useAsync(useCallback((signal: AbortSignal) => enabled
    ? getJSON<AudiencesResponse>('/api/audiences', signal).then(result => result.audiences.filter(audience => !audience.retired))
    : Promise.resolve([]), [enabled]));
}

export function MediaPanel({ kind, id }: { kind: MediaTargetKind; id: string }) {
  const me = useMe();
  const editable = canEditMedia(me);
  const { state, reload } = useAsync(useCallback((signal: AbortSignal) => media.attached(kind, id, signal), [kind, id]));
  const audienceLoad = useAudiences(editable);
  const items = dataOf(state);
  const audiences = dataOf(audienceLoad.state) || [];
  return <section className="media-panel" aria-label="Media">
    <h2 className="section-label">Media <span className="ct">{items?.length || 0}</span></h2>
    {state.status === 'loading' && !items && <Loading what="media" />}
    {state.status === 'error' && <LoadError error={state.error} what="media" onRetry={reload} />}
    {audienceLoad.state.status === 'error' && editable && <LoadError error={audienceLoad.state.error} what="audiences" onRetry={audienceLoad.reload} />}
    {items?.map(item => <MediaItem key={item.id} item={item} audiences={audiences} editable={editable} admin={false} library={false} panelTarget={{ kind, id }} onChanged={reload} />)}
    {items?.length === 0 && <p className="muted small">No media attached.</p>}
    {editable && <UploadForm target={{ kind, id }} onUploaded={reload} />}
  </section>;
}

export function MediaLibrary({ show }: { show: MediaFilter }) {
  const me = useMe();
  const editable = canEditMedia(me);
  const { state, reload } = useAsync(useCallback((signal: AbortSignal) => media.library(show, signal), [show]));
  const audienceLoad = useAudiences(editable);
  const items = dataOf(state);
  const audiences = dataOf(audienceLoad.state) || [];
  return <main className="page media-library">
    <PageHeader eyebrow="Curate" title="Media" blurb="Screenshots and recordings attached to the knowledge base." />
    <nav className="tabs media-tabs" aria-label="Media filters">{FILTERS.map(filter => <Link key={filter.id} to={{ view: 'media', show: filter.id }} className={show === filter.id ? 'on' : undefined}>{filter.label}</Link>)}</nav>
    {editable && <UploadForm onUploaded={reload} />}
    {state.status === 'loading' && !items && <Loading what="media" />}
    {state.status === 'error' && <LoadError error={state.error} what="media" onRetry={reload} />}
    {audienceLoad.state.status === 'error' && editable && <LoadError error={audienceLoad.state.error} what="audiences" onRetry={audienceLoad.reload} />}
    {items?.length === 0 && <EmptyState title="No media in this view" blurb="Try another filter or upload a screenshot or recording." />}
    <div className="media-list">{items?.map(item => <Card key={item.id}><MediaItem item={item} audiences={audiences} editable={editable} admin={me?.role === 'admin'} library onChanged={reload} /></Card>)}</div>
  </main>;
}
