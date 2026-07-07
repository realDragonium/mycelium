// Pending mentions screen — review SUSPECT mention matches.
//
// Mentions are derived from statement text automatically. A match on a
// short/common ("suspect") entity name is too ambiguous to auto-link, so it
// is held here for a human to approve (materialize the mention) or reject
// (write nothing). The same word can be a real reference in one statement and
// noise in another, so review is per (statement, name) occurrence.

const { useState: usePM, useEffect: useEPM, useCallback: useCBPM, useMemo: useMPM } = React;


async function _fetchPending(status) {
  const url = status && status !== 'all'
    ? `/api/pending-mentions?status=${status}`
    : '/api/pending-mentions?status=all';
  const r = await fetch(url);
  if (!r.ok) {
    let d; try { d = (await r.json()).detail; } catch (_) { d = r.statusText; }
    throw new Error(d || `${url} → ${r.status}`);
  }
  return r.json();
}

async function _patchPending(id, action) {
  const r = await fetch(`/api/pending-mentions/${id}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify({ action }),
  });
  if (!r.ok) {
    let d; try { d = (await r.json()).detail; } catch (_) { d = r.statusText; }
    throw new Error(d || `PATCH ${id} → ${r.status}`);
  }
  return r.json();
}


function PendingStatusBadge({ status }) {
  const styles = {
    open:     { bg: 'rgba(217,119,6,0.16)', fg: '#d97706' },
    approved: { bg: 'rgba(22,163,74,0.16)', fg: '#16a34a' },
    rejected: { bg: 'rgba(107,114,128,0.18)', fg: 'var(--ink-3)' },
  };
  const s = styles[status] || styles.open;
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 4,
      fontFamily: 'var(--mono)', fontSize: 10.5, fontWeight: 600,
      letterSpacing: '0.04em', textTransform: 'uppercase',
      background: s.bg, color: s.fg,
    }}>{status}</span>
  );
}


// Highlight the suspect name where it appears in the statement text, so the
// reviewer sees the occurrence in context.
function _highlightName(text, name) {
  const idx = text.toLowerCase().indexOf((name || '').toLowerCase());
  if (idx < 0 || !name) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark style={{ background: 'rgba(37,99,235,0.18)', color: 'inherit', padding: '0 2px', borderRadius: 3 }}>
        {text.slice(idx, idx + name.length)}
      </mark>
      {text.slice(idx + name.length)}
    </>
  );
}


function PendingCard({ row, onAction, busy }) {
  const when = (row.created_at || '').slice(0, 16).replace('T', ' ');
  return (
    <li style={{
      listStyle: 'none', padding: '14px 16px', borderRadius: 6,
      background: row.status === 'open' ? 'var(--surface)' : 'var(--surface-2)',
      border: '1px solid var(--rule)',
      marginBottom: 10, opacity: row.status === 'open' ? 1 : 0.7,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, lineHeight: 1.55, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {_highlightName(row.statement_text, row.name)}
          </div>
          <div style={{
            fontSize: 11.5, color: 'var(--ink-3)', marginTop: 8,
            fontFamily: 'var(--mono)', display: 'flex', gap: 14, flexWrap: 'wrap',
          }}>
            <span>name <strong>{row.name}</strong> → {row.entity_id?.slice(0, 12)}</span>
            <span>found {when}</span>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flexShrink: 0 }}>
          <PendingStatusBadge status={row.status} />
          {row.status === 'open' && (
            <div style={{ display: 'flex', gap: 6 }}>
              <button
                onClick={() => onAction(row.id, 'approve')}
                disabled={busy}
                style={{ fontSize: 11, padding: '4px 10px' }}
                title="This text really refers to the entity — create the mention."
              >Approve</button>
              <button
                onClick={() => onAction(row.id, 'reject')}
                disabled={busy}
                style={{ fontSize: 11, padding: '4px 10px' }}
                title="Noise, not a reference to the entity — write no mention."
              >Reject</button>
            </div>
          )}
        </div>
      </div>
    </li>
  );
}


function PendingMentionsScreen() {
  const [filter, setFilter] = usePM('open');
  const [rows, setRows] = usePM([]);
  const [err, setErr] = usePM(null);
  const [loading, setLoading] = usePM(true);
  const [busyId, setBusyId] = usePM(null);

  const reload = useCBPM(async (statusFilter) => {
    setLoading(true); setErr(null);
    try {
      const data = await _fetchPending(statusFilter);
      setRows(data.pending_mentions || []);
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEPM(() => { reload(filter); }, [filter, reload]);

  const onAction = async (id, action) => {
    setBusyId(id); setErr(null);
    try {
      await _patchPending(id, action);
      await reload(filter);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusyId(null);
    }
  };

  const FILTERS = [
    { id: 'open', label: 'Open' },
    { id: 'approved', label: 'Approved' },
    { id: 'rejected', label: 'Rejected' },
    { id: 'all', label: 'All' },
  ];

  return (
    <main className="page">
      <div className="page-inner" style={{ maxWidth: 880, padding: '32px 24px 80px' }}>
        <header style={{ marginBottom: 18 }}>
          <h1 style={{ margin: 0 }}>Pending mentions</h1>
          <p style={{ marginTop: 6, color: 'var(--ink-3)', fontSize: 13 }}>
            A statement's text matched a short or common entity name — too ambiguous to link on its own. Approve to record the mention, or reject if the word here doesn't really refer to that entity.
          </p>
        </header>

        <div style={{ display: 'flex', gap: 4, marginBottom: 18, borderBottom: '1px solid var(--rule)' }}>
          {FILTERS.map(f => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              style={{
                padding: '8px 14px', fontSize: 13, border: 'none',
                background: 'transparent', cursor: 'pointer',
                color: filter === f.id ? 'var(--ink)' : 'var(--ink-3)',
                borderBottom: filter === f.id ? '2px solid var(--accent, #2563eb)' : '2px solid transparent',
                marginBottom: -1,
              }}
            >{f.label}</button>
          ))}
        </div>

        {err && <div style={{ color: 'var(--red, #dc2626)', fontSize: 13, marginBottom: 12 }}>{err}</div>}

        {loading ? (
          <div style={{ color: 'var(--ink-3)', fontSize: 13 }}>loading…</div>
        ) : rows.length === 0 ? (
          <div style={{ color: 'var(--ink-3)', fontSize: 13, fontStyle: 'italic' }}>
            {filter === 'open' ? 'Nothing to review. Every suspect match has been decided.' : `No ${filter} occurrences.`}
          </div>
        ) : (
          <ul style={{ padding: 0, margin: 0 }}>
            {rows.map(r => (
              <PendingCard key={r.id} row={r} onAction={onAction} busy={busyId === r.id} />
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}


window.PendingMentionsScreen = PendingMentionsScreen;
