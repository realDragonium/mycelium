// Glossary management screen — CRUD UI for the three DB-backed glossary
// tables (statement kinds, statement link types, entity link types).
// Reads from /list-statement-kinds, /list-link-types,
// /list-entity-link-types; mutates via /upsert-* and /delete-*.

const { useState: useG, useEffect: useEG, useCallback: useCBG, useRef: useRG } = React;

const GLOSSARY_TABS = [
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

async function fetchGlossary(endpoint) {
  const r = await fetch(endpoint, { headers: { accept: 'application/json' } });
  if (!r.ok) throw new Error(`GET ${endpoint} → ${r.status}`);
  return r.json();
}

async function postJSON(endpoint, body) {
  const r = await fetch(endpoint, {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail;
    try { detail = (await r.json()).detail; } catch (_) { detail = r.statusText; }
    throw new Error(detail || `POST ${endpoint} → ${r.status}`);
  }
  return r.json();
}

function GlossaryScreen() {
  const [activeTab, setActiveTab] = useG(GLOSSARY_TABS[0].id);
  const tab = GLOSSARY_TABS.find(t => t.id === activeTab);

  return (
    <main className="page">
      <div className="page-inner" style={{maxWidth: 1040, padding: '32px 24px 80px'}}>
        <header className="gls-header">
          <h1>Glossary</h1>
          <p>
            Authoritative definitions for statement kinds and link types in the substrate. Edit a description below, or add a new entry at the bottom of each section. Changes are persisted immediately.
          </p>
        </header>

        <nav className="glossary-tabs">
          {GLOSSARY_TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={t.id === activeTab ? 'is-active' : ''}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <GlossaryTab key={tab.id} tab={tab} />
      </div>
    </main>
  );
}

function GlossaryTab({ tab }) {
  const [entries, setEntries] = useG(null);
  const [error, setError] = useG(null);
  const [loading, setLoading] = useG(true);

  const reload = useCBG(async () => {
    setError(null);
    try {
      const data = await fetchGlossary(tab.endpoints.list);
      const list = Array.isArray(data) ? data : (data.result || []);
      setEntries(list);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [tab.endpoints.list]);

  useEG(() => { setLoading(true); reload(); }, [reload]);

  if (loading) {
    return <div style={{padding: '20px 4px', color: 'var(--ink-3)', fontSize: 13}}>Loading…</div>;
  }
  if (error) {
    return <div className="gls-error" style={{padding: '20px 4px'}}>Error: {error}</div>;
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
            <th style={{width: 1}}></th>
          </tr>
        </thead>
        <tbody>
          {entries.map(e => (
            <GlossaryRow
              key={e[tab.keyField]}
              tab={tab}
              entry={e}
              onSaved={reload}
            />
          ))}
        </tbody>
      </table>

      <div className="gls-card">
        <h3>Add new entry</h3>
        <NewEntryForm tab={tab} onSaved={reload} />
      </div>
    </div>
  );
}

function GlossaryRow({ tab, entry, onSaved }) {
  const [editing, setEditing] = useG(false);
  const [description, setDescription] = useG(entry.description || '');
  const [whenToUse, setWhenToUse] = useG(entry.when_to_use || '');
  const [busy, setBusy] = useG(false);
  const [error, setError] = useG(null);
  // Two-step delete confirm — first click arms the button, second click
  // (within ~3.5s) actually deletes. Auto-disarms on timeout or when the
  // user clicks elsewhere. Cleaner than window.confirm and keeps the
  // user inside the page flow.
  const [confirmingDelete, setConfirmingDelete] = useG(false);
  const confirmTimerRef = useRG(null);

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
      const body = { [tab.keyField]: entry[tab.keyField], description };
      if (tab.hasWhenToUse) body.when_to_use = whenToUse || null;
      await postJSON(tab.endpoints.upsert, body);
      setEditing(false);
      onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async () => {
    cancelDelete();
    setBusy(true); setError(null);
    try {
      await postJSON(tab.endpoints.remove, { [tab.keyField]: entry[tab.keyField] });
      onSaved();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <tr className={editing ? 'is-editing' : ''}>
      <td className="col-key">
        <span className="gls-keytag">{entry[tab.keyField]}</span>
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
      <td className="col-actions">
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
      </td>
    </tr>
  );
}

function NewEntryForm({ tab, onSaved }) {
  const [key, setKey] = useG('');
  const [description, setDescription] = useG('');
  const [whenToUse, setWhenToUse] = useG('');
  const [busy, setBusy] = useG(false);
  const [error, setError] = useG(null);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const body = { [tab.keyField]: key.trim(), description };
      if (tab.hasWhenToUse) body.when_to_use = whenToUse || null;
      await postJSON(tab.endpoints.upsert, body);
      setKey(''); setDescription(''); setWhenToUse('');
      onSaved();
    } catch (e) {
      setError(e.message);
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

Object.assign(window, { GlossaryScreen });
