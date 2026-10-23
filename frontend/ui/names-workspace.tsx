import React from 'react';
import { AliasSuggestions } from './alias-suggestions';
import {
  errorMessage, namesWorkspace,
  type DuplicateCandidate, type DuplicateMatch, type MentionCandidate, type MentionCandidatePage, type NameAction, type NameActionKind,
  type NamesCatalogue, type NamesDetail, type NamesExample, type NamesPreview,
  type NamesRelationship, type WorkspaceConcept,
} from './api';
import { PageHeader } from './lib';
import { Link } from './router';
import { dataOf, useAsync } from './use-async';

const isAbortError = (error: unknown) => error instanceof Error && error.name === 'AbortError';
const isNameActionKind = (value: string): value is NameActionKind =>
  ['add', 'correct', 'prefer', 'move', 'split', 'merge', 'remove'].includes(value);

function NamesExamples({examples, count}: { examples: NamesExample[]; count: number }) {
  return <div><p>{count} possible text matches{count > examples.length ? `, showing ${examples.length}` : ''}. These are examples, not confirmed references.</p>
    <ul className="names-examples">{examples.map(item => <li key={item.id}><p>{item.text}</p><small>{item.kind} · {item.id}</small></li>)}</ul></div>;
}

function NamesRelationships({items, entities}: { items: NamesRelationship[]; entities: WorkspaceConcept[] }) {
  const label = (id: string) => entities.find(entity => entity.id === id)?.label || id;
  return items.length ? <ul>{items.map((item, index) => <li key={index}>{label(item.source)} → {item.link_type} → {label(item.target)}</li>)}</ul> : <p>No concept relationships.</p>;
}

interface NamesEditorProps {
  entity: WorkspaceConcept;
  entities: WorkspaceConcept[];
  allowedActions: NameActionKind[];
  onChanged: (id?: string, documentsUnanchored?: number) => void;
  initialPreview?: NamesPreview;
}

function NamesEditor({entity, entities, allowedActions, onChanged, initialPreview}: NamesEditorProps) {
  const merge = initialPreview?.action.kind === 'merge' ? initialPreview.action : null;
  const [kind, setKind] = React.useState<NameActionKind>(merge ? 'merge' : 'add');
  const [nameId, setNameId] = React.useState('');
  const [text, setText] = React.useState('');
  const [target, setTarget] = React.useState(merge?.target_entity_id ?? '');
  const [selected, setSelected] = React.useState<string[]>([]);
  const [preferred, setPreferred] = React.useState(merge?.preferred_name_id ?? '');
  const [description, setDescription] = React.useState(merge?.description ?? '');
  const [preview, setPreview] = React.useState<NamesPreview | null>(initialPreview ?? null);
  const revealInitial = React.useCallback((node: HTMLDivElement | null) => { if (node && initialPreview) node.scrollIntoView({block: 'nearest'}); }, [initialPreview]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const inFlight = React.useRef(false);
  const authored = entity.names.filter(name => !name.generated_from_name_id);
  const destination = entities.find(item => item.id === target);
  const preferredOptions = kind === 'merge' ? [...authored, ...(destination?.names || []).filter(name => !name.generated_from_name_id)] : authored.filter(name => selected.includes(name.id));
  const changeKind = (value: NameActionKind) => { setKind(value); setPreview(null); setError(null); setNameId(''); setText(''); setPreferred(''); setSelected([]); setTarget(''); setDescription(''); };
  const change = (setter: React.Dispatch<React.SetStateAction<string>>) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => { setter(event.target.value); setPreview(null); setError(null); };
  const action = (): NameAction => {
    if (kind === 'add') return {kind, entity_id: entity.id, text};
    if (kind === 'correct') return {kind, entity_id: entity.id, name_id: nameId, text};
    if (kind === 'move') return {kind, entity_id: entity.id, name_id: nameId, target_entity_id: target};
    if (kind === 'split') return {kind, entity_id: entity.id, name_ids: selected, preferred_name_id: preferred, description};
    if (kind === 'merge') return {kind, entity_id: entity.id, target_entity_id: target, preferred_name_id: preferred, description};
    return {kind, entity_id: entity.id, name_id: nameId};
  };
  const run = async (apply: boolean) => {
    const currentPreview = preview;
    if (apply && !currentPreview) return;
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(null);
    try {
      if (apply) {
        if (!currentPreview) return;
        const result = await namesWorkspace.apply(currentPreview.action, currentPreview.revision); setPreview(null); onChanged(result.entity_id, result.documents_unanchored);
      } else setPreview(await namesWorkspace.preview(action()));
    } catch (error) { setError(errorMessage(error)); if (apply) setPreview(null); }
    finally { inFlight.current = false; setBusy(false); }
  };
  return <section className="names-panel"><h3>Edit names</h3>{!allowedActions.includes("merge") && <p>Admin access is required to merge concepts or remove aliases.</p>}
    <form onSubmit={event => {event.preventDefault(); run(false);}}><fieldset disabled={busy}>
      <label>Action<select aria-label="Action" value={kind} onChange={event => { if (isNameActionKind(event.target.value)) changeKind(event.target.value); }}>
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
    {preview && <div className="names-preview" ref={revealInitial}><h3>Review change</h3><p>{preview.summary}</p>
      <p>Names: {preview.names.map(name => name.text).join(', ') || 'None'}</p>
      {(preview.action.kind === 'merge' || preview.action.kind === 'split') && <p>Description: {preview.action.description || 'Empty description'}</p>}
      {preview.warnings.map(warning => <p key={warning}>{warning}</p>)}
      {preview.action.kind === 'merge' && <><h4>Relationships before</h4><NamesRelationships items={preview.relationships_before} entities={entities}/><h4>Relationships after</h4><NamesRelationships items={preview.relationships_after} entities={entities}/></>}
      <NamesExamples examples={preview.examples} count={preview.example_count}/>
      <button disabled={busy} onClick={() => run(true)}>Apply reviewed change</button><button disabled={busy} onClick={() => setPreview(null)}>Cancel</button>
    </div>}
  </section>;
}

function NamesDiscovery({entityId}: { entityId: string }) {
  const [after, setAfter] = React.useState(0);
  const [items, setItems] = React.useState<MentionCandidate[]>([]);
  const [page, setPage] = React.useState<MentionCandidatePage | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [retry, setRetry] = React.useState(0);
  React.useEffect(() => {
    const controller = new AbortController(); setBusy(true); setError(null);
    namesWorkspace.mentionCandidates(entityId, after, controller.signal)
      .then(value => {setItems(previous => after ? [...previous, ...value.matches] : value.matches); setPage(value);})
      .catch(error => {if (!isAbortError(error)) setError(errorMessage(error));})
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

interface NamesConceptProps extends Omit<NamesEditorProps, 'entity'> { id: string; canWrite: boolean; refresh: number }

function NamesConcept({id, entities, canWrite, allowedActions, refresh, onChanged, initialPreview}: NamesConceptProps) {
  const [detail, setDetail] = React.useState<NamesDetail | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    const controller = new AbortController(); setDetail(null); setError(null);
    namesWorkspace.detail(id, controller.signal).then(setDetail).catch(error => {if (!isAbortError(error)) setError(errorMessage(error));});
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
  {canWrite && <NamesEditor key={id + ':' + detail.revision} entity={entity} entities={entities} allowedActions={allowedActions} onChanged={onChanged} initialPreview={initialPreview}/>}
  <section className="names-panel"><h3>Change history</h3>{!detail.history_available ? <p>No history archive is attached.</p> : !detail.history.length ? <p>No recorded changes.</p> : <ul>{detail.history.map((item, index) => <li key={index}><details><summary>{new Date(item.at).toLocaleString()} · {item.op} · {item.actor || 'Actor not recorded'}</summary>{item.context_json && <pre>{item.context_json}</pre>}<p>Before</p><pre>{item.before_json || 'Not recorded'}</pre><p>After</p><pre>{item.after_json || 'Not recorded'}</pre></details></li>)}</ul>}</section></div>;
}

const matchReason = (match: DuplicateMatch) => ({
  fold: 'same words once case and punctuation are ignored',
  same_words: 'same words in another order or spelling style',
  initials: 'one spells the initials of the other',
  embedding: `similar meaning (${Math.round(match.score * 100)}%)`,
})[match.via];

const DUPLICATES_PAGE = 50;

interface NamesDuplicatesProps {
  entities: WorkspaceConcept[];
  canWrite: boolean;
  canMerge: boolean;
  onReview: (preview: NamesPreview) => void;
}

function NamesDuplicates({entities, canWrite, canMerge, onReview}: NamesDuplicatesProps) {
  const [limit, setLimit] = React.useState(DUPLICATES_PAGE);
  const {state, reload, update} = useAsync(React.useCallback((signal: AbortSignal) => namesWorkspace.duplicates(limit, signal), [limit]));
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const page = dataOf(state);
  const candidates = page?.candidates;
  const byId = new Map(entities.map(entity => [entity.id, entity]));
  const label = (id: string) => byId.get(id)?.label || id;
  const act = async (work: () => Promise<void>) => {
    if (busy) return;
    setBusy(true); setError(null);
    try { await work(); } catch (error) { setError(errorMessage(error)); } finally { setBusy(false); }
  };
  const merge = (sourceId: string, targetId: string) => act(async () => {
    const source = byId.get(sourceId), target = byId.get(targetId);
    if (!source || !target) throw new Error('A concept changed since this list loaded. Reload the page.');
    const authored = [target, source].flatMap(entity => entity.names.filter(name => !name.generated_from_name_id));
    const preferred = authored.find(name => name.id === target.preferred_name_id) || authored[0];
    if (!preferred) throw new Error('Neither concept has an authored name to keep.');
    onReview(await namesWorkspace.preview({
      kind: 'merge', entity_id: source.id, target_entity_id: target.id,
      preferred_name_id: preferred.id, description: target.description || source.description,
    }));
  });
  const dismiss = (candidate: DuplicateCandidate) => act(async () => {
    await namesWorkspace.dismissDuplicate(candidate.a_entity_id, candidate.b_entity_id);
    update(current => ({candidates: current.candidates.filter(item => item !== candidate), total: current.total - 1}));
  });
  return <section className="names-panel"><p>Concepts whose names look alike. Review a merge, or mark a pair as not a duplicate so it stops appearing here.</p>
    {!canMerge && canWrite && <p>Admin access is required to merge concepts.</p>}
    {error && <p role="alert">{error}</p>}
    {state.status === 'error' && <p role="alert">{errorMessage(state.error)} <button onClick={reload}>Retry</button></p>}
    {!candidates ? state.status === 'loading' && <p>Finding possible duplicates…</p> : !candidates.length ? <p>No possible duplicates found.</p> :
      <ul className="names-duplicates">{candidates.map(candidate => {
        const [a, b] = [candidate.a_entity_id, candidate.b_entity_id];
        return <li key={a + ':' + b}>
          <p><b>{label(a)}</b> and <b>{label(b)}</b></p>
          <ul>{candidate.matches.map((match, index) => <li key={index}>“{match.a_name}” and “{match.b_name}”: {matchReason(match)}</li>)}</ul>
          {[a, b].map(id => byId.get(id)?.description && <small key={id}>{label(id)}: {byId.get(id)?.description}</small>)}
          <div className="names-duplicate-actions">
            {canMerge && <><button disabled={busy} onClick={() => merge(a, b)}>Merge {label(a)} into {label(b)}</button><button disabled={busy} onClick={() => merge(b, a)}>Merge {label(b)} into {label(a)}</button></>}
            {canWrite && <button disabled={busy} onClick={() => dismiss(candidate)}>Not a duplicate</button>}
          </div>
        </li>;
      })}</ul>}
    {page && candidates && candidates.length < page.total && <p>Showing {candidates.length} of {page.total} possible duplicates. <button disabled={state.status === 'loading'} onClick={() => setLimit(candidates.length + DUPLICATES_PAGE)}>Show more</button></p>}
  </section>;
}

function NamesWorkspace({onDataChanged}: { onDataChanged?: () => Promise<void> }) {
  const [catalogue, setCatalogue] = React.useState<NamesCatalogue | null>(null);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState('');
  const [tab, setTab] = React.useState<'names' | 'duplicates' | 'suggestions'>('names');
  const [pendingMerge, setPendingMerge] = React.useState<NamesPreview | null>(null);
  const [refresh, setRefresh] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  React.useEffect(() => {
    const controller = new AbortController(); setError(null);
    namesWorkspace.catalogue(controller.signal).then(setCatalogue).catch(error => {if (!isAbortError(error)) setError(errorMessage(error));});
    return () => controller.abort();
  }, [refresh]);
  const [unanchored, setUnanchored] = React.useState(0);
  const changed = (id?: string, documentsUnanchored = 0) => {setPendingMerge(null); if (id) setSelected(id); setRefresh(value => value + 1); setUnanchored(documentsUnanchored); setNotice('Change saved. Discovery is being recomputed.'); if (onDataChanged) onDataChanged().catch(() => setNotice('Change saved. Reload the page to refresh other views.'));};
  const filtered = (catalogue?.entities || []).filter(entity => (entity.label + ' ' + entity.description + ' ' + entity.names.map(name => name.text).join(' ')).toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <main className="page names-workspace"><PageHeader eyebrow="Curate" title="Names & aliases" blurb="Keep every name for a concept together: add, correct, move or merge aliases, and decide AI alias suggestions. Statements keep their original wording; mentions follow the names." />
    <nav className="tabs" aria-label="Names workspace"><button className={tab === 'names' ? 'on' : ''} aria-pressed={tab === 'names'} onClick={() => setTab('names')}>Names</button><button className={tab === 'duplicates' ? 'on' : ''} aria-pressed={tab === 'duplicates'} onClick={() => setTab('duplicates')}>Possible duplicates</button><button className={tab === 'suggestions' ? 'on' : ''} aria-pressed={tab === 'suggestions'} onClick={() => setTab('suggestions')}>AI suggestions</button></nav>
    {error && <p role="alert">{error} <button onClick={() => setRefresh(value => value + 1)}>Retry</button></p>}
    {notice && <p role="status">{notice}</p>}
    {unanchored > 0 && <p role="status">{unanchored === 1 ? '1 document' : `${unanchored} documents`} lost {unanchored === 1 ? 'its' : 'their'} concept anchor. <Link to={{ view: 'documentation' }}>Review in Documents</Link></p>}
    {!catalogue ? <p>Loading names…</p> : tab === 'suggestions' ? <AliasSuggestions canWrite={catalogue.can_write} onChanged={() => changed()}/>
      : tab === 'duplicates' ? <NamesDuplicates entities={catalogue.entities} canWrite={catalogue.can_write} canMerge={catalogue.allowed_actions.includes('merge')} onReview={preview => {setPendingMerge(preview); setSelected(preview.action.entity_id); setNotice(null); setUnanchored(0); setTab('names');}}/> : <>
      {!catalogue.can_write && <p>Writer or admin access is required to edit names.</p>}
      <div className="names-layout"><aside><label>Find a name or alias<input type="search" value={query} onChange={event => setQuery(event.target.value)}/></label><p>{filtered.length} concepts</p><ul className="names-catalogue">{filtered.map(entity => <li key={entity.id}><button aria-current={selected === entity.id ? 'true' : undefined} onClick={() => {setSelected(entity.id); setPendingMerge(null); setNotice(null); setUnanchored(0);}}><b>{entity.label}</b><small>{entity.names.filter(name => !name.generated_from_name_id && name.text !== entity.label).map(name => name.text).join(', ') || 'No other authored names'}</small></button></li>)}</ul></aside>
      {selected ? <NamesConcept id={selected} entities={catalogue.entities} canWrite={catalogue.can_write} allowedActions={catalogue.allowed_actions} refresh={refresh} onChanged={changed} initialPreview={pendingMerge?.action.entity_id === selected ? pendingMerge : undefined}/> : <p>Select a concept to inspect its names and examples.</p>}
      </div>
    </>}
  </main>;
}

export { NamesWorkspace };
