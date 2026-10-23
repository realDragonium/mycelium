// Glossary management screen — CRUD UI for the three DB-backed glossary
// tables (statement kinds, statement link types, entity link types).
// Reads from /list-statement-kinds, /list-link-types,
// /list-entity-link-types; mutates via /upsert-* and /delete-*.
import { errorMessage, getJSON, isScoped, postJSON } from './api';
import { PageHeader, useMe } from './lib';
import { useState as useG, useEffect as useEG, useCallback as useCBG, useRef as useRG, type FormEvent } from 'react';

type GlossaryTabId = 'kinds' | 'link_types' | 'entity_link_types';
interface GlossaryTab {
  id: GlossaryTabId;
  label: string;
  keyField: 'kind' | 'link_type';
  keyLabel: string;
  hasWhenToUse: boolean;
  endpoints: { list: string; upsert: string; remove: string };
  addPlaceholder: string;
}

const GLOSSARY_TABS: readonly GlossaryTab[] = [
  {
    id: 'kinds',
    label: 'Statement kinds',
    keyField: 'kind',
    keyLabel: 'kind',
    hasWhenToUse: true,
    endpoints: {
      list: '/list-statement-kinds',
      upsert: '/upsert-statement-kind',
      remove: '/delete-statement-kind',
    },
    addPlaceholder: 'e.g. policy',
  },
  {
    id: 'link_types',
    label: 'Statement link types',
    keyField: 'link_type',
    keyLabel: 'link type',
    hasWhenToUse: false,
    endpoints: {
      list: '/list-link-types',
      upsert: '/upsert-link-type',
      remove: '/delete-link-type',
    },
    addPlaceholder: 'e.g. caused-by',
  },
  {
    id: 'entity_link_types',
    label: 'Entity link types',
    keyField: 'link_type',
    keyLabel: 'link type',
    hasWhenToUse: false,
    endpoints: {
      list: '/list-entity-link-types',
      upsert: '/upsert-entity-link-type',
      remove: '/delete-entity-link-type',
    },
    addPlaceholder: 'e.g. owned-by',
  },
];

interface GlossaryEntry {
  kind?: string;
  link_type?: string;
  description: string;
  when_to_use?: string;
  usage_count: number;
}

type GlossaryResponse = GlossaryEntry[] | { result?: GlossaryEntry[] };

const entryKey = (tab: GlossaryTab, entry: GlossaryEntry): string =>
  tab.keyField === 'kind' ? entry.kind || '' : entry.link_type || '';

async function fetchGlossary(endpoint: string): Promise<GlossaryEntry[]> {
  const data = await getJSON<GlossaryResponse>(endpoint);
  return Array.isArray(data) ? data : (data.result || []);
}

function GlossaryScreen() {
  const readOnly = isScoped(useMe());
  const [activeTab, setActiveTab] = useG<GlossaryTabId>('kinds');
  const tab = GLOSSARY_TABS.find(t => t.id === activeTab);

  if (!tab) return null;

  return (
    <main className="page">
      <PageHeader eyebrow="Curate" title="Glossary"
        blurb={readOnly ? 'The vocabulary the knowledge base is written in: statement kinds, statement link types and entity link types.' : 'The vocabulary the knowledge base is written in: statement kinds, statement link types and entity link types. Edit a description, or add an entry at the end of a section. Changes save immediately and are offered to every agent.'} />
      <nav className="tabs">
        {GLOSSARY_TABS.map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)} className={t.id === activeTab ? 'on' : ''} aria-pressed={t.id === activeTab}>{t.label}</button>
        ))}
      </nav>
      <GlossaryTab key={tab.id} tab={tab} readOnly={readOnly} />
    </main>
  );
}

function GlossaryTab({ tab, readOnly }: { tab: GlossaryTab; readOnly: boolean }) {
  const [entries, setEntries] = useG<GlossaryEntry[]>([]);
  const [error, setError] = useG<string | null>(null);
  const [loading, setLoading] = useG(true);

  const reload = useCBG(async () => {
    setError(null);
    try {
      setEntries(await fetchGlossary(tab.endpoints.list));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [tab.endpoints.list]);

  useEG(() => { setLoading(true); reload(); }, [reload]);

  if (loading) {
    return <p className="muted small" role="status">Loading…</p>;
  }
  if (error) {
    return <p className="gls-error" role="alert">Error: {error}</p>;
  }

  const totalUsage = entries.reduce((acc, e) => acc + (e.usage_count || 0), 0);
  const unusedCount = entries.filter(e => !e.usage_count).length;

  return (
    <div>
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'baseline', marginBottom: 10, fontSize: 12, color: 'var(--ink-3)'}}>
        <span>
          {entries.length} {entries.length === 1 ? 'entry' : 'entries'}
          {' · '}
          {totalUsage.toLocaleString()} {tab.id === 'kinds' ? 'statement' : 'link'}{totalUsage === 1 ? '' : 's'} total
          {unusedCount > 0 && ` · ${unusedCount} not yet used`}
        </span>
      </div>

      <table className="glossary-table">
        <thead>
          <tr>
            <th>{tab.keyLabel}</th>
            <th>Description</th>
            {tab.hasWhenToUse && <th>When to use</th>}
            <th style={{width: 110, textAlign: 'right'}}>Usage</th>
            {!readOnly && <th style={{width: 1}}></th>}
          </tr>
        </thead>
        <tbody>
          {entries.map(e => (
            <GlossaryRow
              key={entryKey(tab, e)}
              tab={tab}
              entry={e}
              readOnly={readOnly}
              onSaved={reload}
            />
          ))}
        </tbody>
      </table>

      {!readOnly && <div className="gls-card">
        <h3>Add new entry</h3>
        <NewEntryForm tab={tab} onSaved={reload} />
      </div>}
    </div>
  );
}

interface GlossaryRowProps {
  tab: GlossaryTab;
  entry: GlossaryEntry;
  readOnly: boolean;
  onSaved: () => void;
}

function GlossaryRow({ tab, entry, readOnly, onSaved }: GlossaryRowProps) {
  const [editing, setEditing] = useG(false);
  const [description, setDescription] = useG(entry.description || '');
  const [whenToUse, setWhenToUse] = useG(entry.when_to_use || '');
  const [busy, setBusy] = useG(false);
  const [error, setError] = useG<string | null>(null);
  // Two-step delete confirm — first click arms the button, second click
  // (within ~3.5s) actually deletes. Auto-disarms on timeout or when the
  // user clicks elsewhere. Cleaner than window.confirm and keeps the
  // user inside the page flow.
  const [confirmingDelete, setConfirmingDelete] = useG(false);
  const confirmTimerRef = useRG<ReturnType<typeof setTimeout> | null>(null);

  const armDelete = () => {
    if (confirmTimerRef.current) clearTimeout(confirmTimerRef.current);
    setConfirmingDelete(true);
    confirmTimerRef.current = setTimeout(() => setConfirmingDelete(false), 3500);
  };

  const cancelDelete = () => {
    if (confirmTimerRef.current) clearTimeout(confirmTimerRef.current);
    setConfirmingDelete(false);
  };

  useEG(() => () => { if (confirmTimerRef.current) clearTimeout(confirmTimerRef.current); }, []);

  const reset = () => {
    setDescription(entry.description || '');
    setWhenToUse(entry.when_to_use || '');
    setError(null);
    setEditing(false);
  };

  const save = async () => {
    setBusy(true); setError(null);
    try {
      const body: Record<string, unknown> = { [tab.keyField]: entryKey(tab, entry), description };
      if (tab.hasWhenToUse) body.when_to_use = whenToUse || null;
      await postJSON(tab.endpoints.upsert, body);
      setEditing(false);
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async () => {
    cancelDelete();
    setBusy(true); setError(null);
    try {
      await postJSON<unknown>(tab.endpoints.remove, { [tab.keyField]: entryKey(tab, entry) });
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };

  return (
    <tr className={editing ? 'is-editing' : ''}>
      <td className="col-key">
        <span className="gls-keytag">{entryKey(tab, entry)}</span>
      </td>
      <td>
        {editing ? (
          <textarea
            value={description}
            onChange={e => setDescription(e.target.value)}
            rows={4}
            className="gls-textarea"
            disabled={busy}
          />
        ) : (
          <div className={`desc ${entry.description ? '' : 'empty'}`}>
            {entry.description || 'no description'}
          </div>
        )}
        {error && <div className="gls-error">{error}</div>}
      </td>
      {tab.hasWhenToUse && (
        <td>
          {editing ? (
            <textarea
              value={whenToUse}
              onChange={e => setWhenToUse(e.target.value)}
              rows={4}
              className="gls-textarea"
              disabled={busy}
              placeholder="optional"
            />
          ) : (
            <div className={`desc ${entry.when_to_use ? '' : 'empty'}`}>
              {entry.when_to_use || '—'}
            </div>
          )}
        </td>
      )}
      <td style={{textAlign: 'right'}}>
        <span className={`gls-count ${entry.usage_count ? '' : 'is-zero'}`}>
          {(entry.usage_count || 0).toLocaleString()}
        </span>
        <span style={{display:'block', marginTop: 2, fontSize: 10.5, color:'var(--ink-4)'}}>
          {tab.id === 'kinds'
            ? (entry.usage_count === 1 ? 'statement' : 'statements')
            : (entry.usage_count === 1 ? 'link' : 'links')}
        </span>
      </td>
      {!readOnly && <td className="col-actions">
        <div className="gls-row-actions">
          {editing ? (
            <>
              <button onClick={save} disabled={busy} className="gls-btn is-primary">Save</button>
              <button onClick={reset} disabled={busy} className="gls-btn">Cancel</button>
            </>
          ) : confirmingDelete ? (
            <>
              <button onClick={doDelete} disabled={busy} className="gls-btn is-confirming" title="Click to confirm deletion">
                {busy ? 'Deleting…' : 'Confirm delete'}
              </button>
              <button onClick={cancelDelete} disabled={busy} className="gls-btn">Cancel</button>
            </>
          ) : (
            <>
              <button onClick={() => setEditing(true)} className="gls-btn">Edit</button>
              <button onClick={armDelete} disabled={busy} className="gls-btn is-danger" title="Delete this glossary entry">Delete</button>
            </>
          )}
        </div>
      </td>}
    </tr>
  );
}

function NewEntryForm({ tab, onSaved }: { tab: GlossaryTab; onSaved: () => void }) {
  const [key, setKey] = useG('');
  const [description, setDescription] = useG('');
  const [whenToUse, setWhenToUse] = useG('');
  const [busy, setBusy] = useG(false);
  const [error, setError] = useG<string | null>(null);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const body: Record<string, unknown> = { [tab.keyField]: key.trim(), description };
      if (tab.hasWhenToUse) body.when_to_use = whenToUse || null;
      await postJSON(tab.endpoints.upsert, body);
      setKey(''); setDescription(''); setWhenToUse('');
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <label className="gls-field">
        {tab.keyLabel}
        <input
          type="text"
          value={key}
          onChange={e => setKey(e.target.value)}
          required
          disabled={busy}
          className="gls-input is-key"
          placeholder={tab.addPlaceholder}
        />
      </label>
      <label className="gls-field">
        description
        <textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          required
          rows={3}
          disabled={busy}
          className="gls-textarea"
        />
      </label>
      {tab.hasWhenToUse && (
        <label className="gls-field">
          when to use <span className="gls-field-hint">(optional)</span>
          <textarea
            value={whenToUse}
            onChange={e => setWhenToUse(e.target.value)}
            rows={3}
            disabled={busy}
            className="gls-textarea"
          />
        </label>
      )}
      {error && <div className="gls-error" style={{marginBottom: 12}}>{error}</div>}
      <button type="submit" disabled={busy || !key.trim() || !description.trim()} className="gls-btn is-primary">
        {busy ? 'Saving…' : 'Add entry'}
      </button>
    </form>
  );
}

export { GlossaryScreen };
