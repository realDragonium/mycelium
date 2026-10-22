// Gaps screen — review knowledge-base gap reports filed by agents
// (via the report_knowledge_gap MCP tool) and humans (via this UI).
//
// Filtering by status (open / resolved / dismissed / all). Inline
// actions: mark resolved, mark dismissed, reopen. No new-gap form
// here on purpose — humans can file via the MCP tool too if they
// want, but the primary intake is automated agents flagging things
// during their work. Editing/curation lives in the substrate proper.

const { useState: useG, useEffect: useEG, useCallback: useCBG, useMemo: useMG } = React;


async function _fetchGaps(status) {
  const url = status && status !== 'all'
    ? `/api/knowledge-gaps?status=${status}`
    : '/api/knowledge-gaps';
  const r = await fetch(url);
  if (!r.ok) {
    let d; try { d = (await r.json()).detail; } catch (_) { d = r.statusText; }
    throw new Error(d || `${url} → ${r.status}`);
  }
  return r.json();
}

async function _patchGap(gapId, action) {
  const r = await fetch(`/api/knowledge-gaps/${gapId}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify({ action }),
  });
  if (!r.ok) {
    let d; try { d = (await r.json()).detail; } catch (_) { d = r.statusText; }
    throw new Error(d || `PATCH ${gapId} → ${r.status}`);
  }
  return r.json();
}


function GapStatusBadge({ status }) {
  const styles = {
    open:      { bg: 'rgba(217,119,6,0.16)', fg: '#d97706' },
    resolved:  { bg: 'rgba(22,163,74,0.16)', fg: '#16a34a' },
    dismissed: { bg: 'rgba(107,114,128,0.18)', fg: 'var(--ink-3)' },
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


function GapCard({ gap, onAction, busy }) {
  // Author hint: the principal id we stored is a UUID, not useful to
  // a human reader on its own. We show it dimly and trust the
  // create-time timestamp to be the more useful trace.
  const author = (gap.created_by || '').slice(0, 8) || '—';
  const when = (gap.created_at || '').slice(0, 16).replace('T', ' ');
  const terminal = gap.resolved_at || gap.dismissed_at;
  const terminalWhen = terminal ? terminal.slice(0, 16).replace('T', ' ') : null;
  const terminalActor = (gap.resolved_by || gap.dismissed_by || '').slice(0, 8);

  return (
    <li style={{
      listStyle: 'none', padding: '14px 16px', borderRadius: 6,
      background: gap.status === 'open' ? 'var(--surface)' : 'var(--surface-2)',
      border: '1px solid var(--rule)',
      marginBottom: 10, opacity: gap.status === 'open' ? 1 : 0.7,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, lineHeight: 1.55, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {gap.text}
          </div>
          <div style={{
            fontSize: 11.5, color: 'var(--ink-3)', marginTop: 8,
            fontFamily: 'var(--mono)', display: 'flex', gap: 14, flexWrap: 'wrap',
          }}>
            <span>filed {when} by {author}</span>
            {terminal && <span>{gap.status} {terminalWhen} by {terminalActor}</span>}
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flexShrink: 0 }}>
          <GapStatusBadge status={gap.status} />
          <div style={{ display: 'flex', gap: 6 }}>
            {gap.status === 'open' && (
              <>
                <button
                  onClick={() => onAction(gap.id, 'resolve')}
                  disabled={busy}
                  style={{ fontSize: 11, padding: '4px 10px' }}
                  title="Mark as resolved — the gap was addressed."
                >Resolve</button>
                <button
                  onClick={() => onAction(gap.id, 'dismiss')}
                  disabled={busy}
                  style={{ fontSize: 11, padding: '4px 10px' }}
                  title="Mark as dismissed — not actually a gap, or won't fix."
                >Dismiss</button>
              </>
            )}
            {gap.status !== 'open' && (
              <button
                onClick={() => onAction(gap.id, 'reopen')}
                disabled={busy}
                style={{ fontSize: 11, padding: '4px 10px' }}
              >Reopen</button>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}


function GapsScreen() {
  const [filter, setFilter] = useG('open');
  const [gaps, setGaps] = useG([]);
  const [err, setErr] = useG(null);
  const [loading, setLoading] = useG(true);
  const [busyId, setBusyId] = useG(null);

  const reload = useCBG(async (statusFilter) => {
    setLoading(true); setErr(null);
    try {
      const data = await _fetchGaps(statusFilter);
      setGaps(data.gaps || []);
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEG(() => { reload(filter); }, [filter, reload]);

  const onAction = async (gapId, action) => {
    setBusyId(gapId); setErr(null);
    try {
      await _patchGap(gapId, action);
      // Refetch with the current filter — if the action moved the
      // row out of the visible filter (e.g. resolved an open one
      // while showing "open"), it should disappear from the list.
      await reload(filter);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusyId(null);
    }
  };

  const counts = useMG(() => {
    const c = { all: gaps.length, open: 0, resolved: 0, dismissed: 0 };
    for (const g of gaps) c[g.status] = (c[g.status] || 0) + 1;
    return c;
  }, [gaps]);

  const FILTERS = [
    { id: 'open', label: 'Open' },
    { id: 'resolved', label: 'Resolved' },
    { id: 'dismissed', label: 'Dismissed' },
    { id: 'all', label: 'All' },
  ];

  return (
    <main className="page">
      <div className="page-inner" style={{ maxWidth: 880, padding: '32px 24px 80px' }}>
        <header style={{ marginBottom: 18 }}>
          <h1 style={{ margin: 0 }}>Gaps</h1>
          <p style={{ marginTop: 6, color: 'var(--ink-3)', fontSize: 13 }}>
            Knowledge-base gap reports filed by callers — agents flag holes via the <code>report_knowledge_gap</code> tool; humans can also file via that same tool. Review, resolve, or dismiss.
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
            >
              {f.label}{filter === 'all' && f.id !== 'all' ? '' : ''}
            </button>
          ))}
        </div>

        {err && <div style={{ color: 'var(--red, #dc2626)', fontSize: 13, marginBottom: 12 }}>{err}</div>}

        {loading ? (
          <div style={{ color: 'var(--ink-3)', fontSize: 13 }}>loading…</div>
        ) : gaps.length === 0 ? (
          <div style={{ color: 'var(--ink-3)', fontSize: 13, fontStyle: 'italic' }}>
            {filter === 'open' ? 'No open gaps. Nothing on the radar right now.' : `No ${filter} gaps.`}
          </div>
        ) : (
          <ul style={{ padding: 0, margin: 0 }}>
            {gaps.map(g => (
              <GapCard key={g.id} gap={g} onAction={onAction} busy={busyId === g.id} />
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}


window.GapsScreen = GapsScreen;
