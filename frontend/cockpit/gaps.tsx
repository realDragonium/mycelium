/**
 * @typedef {'open' | 'resolved' | 'dismissed'} KnowledgeGapStatus
 * @typedef {'resolve' | 'dismiss' | 'reopen'} KnowledgeGapAction
 * @typedef {{id: string, text: string, status: KnowledgeGapStatus,
 *   created_at: string, created_by: string | null,
 *   resolved_at: string | null, dismissed_at: string | null}} KnowledgeGap
 * @typedef {{phase: 'loading'} | {phase: 'error', message: string} |
 *   {phase: 'ready', gaps: KnowledgeGap[]}} KnowledgeGapLoad
 */

/** @type {ReadonlyArray<{id: KnowledgeGapStatus | 'all', label: string}>} */
const GAP_FILTERS = [
  { id: 'open', label: 'Open' },
  { id: 'resolved', label: 'Resolved' },
  { id: 'dismissed', label: 'Dismissed' },
  { id: 'all', label: 'All' },
];

/** @param {unknown} error */
function gapErrorMessage(error) {
  return error instanceof Error ? error.message : 'The request failed. Please try again.';
}

/** @param {{gap: KnowledgeGap, busy: boolean, onAction: (id: string, action: KnowledgeGapAction) => Promise<void>}} props */
function KnowledgeGapCard({ gap, busy, onAction }) {
  const changedAt = gap.resolved_at || gap.dismissed_at;
  return (
    <li className="knowledge-gap-card">
      <div className="knowledge-gap-body">
        <p>{gap.text}</p>
        <div className="knowledge-gap-meta">
          <span>Reported <time dateTime={gap.created_at}>{new Date(gap.created_at).toLocaleString()}</time></span>
          {changedAt && <span>{gap.status} <time dateTime={changedAt}>{new Date(changedAt).toLocaleString()}</time></span>}
          <span className="knowledge-gap-id">{gap.id}</span>
        </div>
      </div>
      <div className="knowledge-gap-controls">
        <span className={`knowledge-gap-status ${gap.status}`}>{gap.status}</span>
        <div className="knowledge-gap-actions">
          {gap.status === 'open' ? <>
            <button className="btn-sm" disabled={busy} onClick={() => onAction(gap.id, 'resolve')}>Resolve</button>
            <button className="btn-sm" disabled={busy} onClick={() => onAction(gap.id, 'dismiss')}>Dismiss</button>
          </> : <button className="btn-sm" disabled={busy} onClick={() => onAction(gap.id, 'reopen')}>Reopen</button>}
        </div>
      </div>
    </li>
  );
}

function KnowledgeGapsScreen() {
  const [filter, setFilter] = React.useState(/** @type {KnowledgeGapStatus | 'all'} */ ('open'));
  const [load, setLoad] = React.useState(/** @type {KnowledgeGapLoad} */ ({ phase: 'loading' }));
  const [attempt, setAttempt] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [actionError, setActionError] = React.useState('');

  React.useEffect(() => {
    let cancelled = false;
    setLoad({ phase: 'loading' });
    window.Myc.knowledgeGaps('all').then(
      /** @param {{gaps: KnowledgeGap[]}} result */
      (result) => { if (!cancelled) setLoad({ phase: 'ready', gaps: result.gaps }); },
      (error) => { if (!cancelled) setLoad({ phase: 'error', message: gapErrorMessage(error) }); },
    );
    return () => { cancelled = true; };
  }, [attempt]);

  /** @param {string} id @param {KnowledgeGapAction} action */
  async function onAction(id, action) {
    setBusy(true);
    setActionError('');
    try {
      /** @type {{gap: KnowledgeGap}} */
      const result = await window.Myc.updateKnowledgeGap(id, action);
      // Use the saved row so a failed follow-up read cannot misreport a successful action.
      setLoad(current => current.phase === 'ready'
        ? { phase: 'ready', gaps: current.gaps.map(gap => gap.id === id ? result.gap : gap) }
        : current);
    } catch (error) {
      setActionError(gapErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  const visible = load.phase === 'ready'
    ? load.gaps.filter(gap => filter === 'all' || gap.status === filter) : [];

  return (
    <main className="page narrow knowledge-gaps">
      <header className="knowledge-gaps-header">
        <h1>Knowledge gaps</h1>
        <p>Reported questions, inconsistencies, and unclear areas. Resolve addressed reports, dismiss those that need no action, or reopen them later.</p>
      </header>
      <div className="knowledge-gaps-toolbar">
        <div className="knowledge-gap-filters" role="group" aria-label="Filter knowledge gaps">
          {GAP_FILTERS.map(item => (
            <button key={item.id} className={`btn-sm${filter === item.id ? ' selected' : ''}`}
              aria-pressed={filter === item.id} onClick={() => setFilter(item.id)}>
              {item.label}
              {load.phase === 'ready' && <span>{load.gaps.filter(gap => item.id === 'all' || gap.status === item.id).length}</span>}
            </button>
          ))}
        </div>
        <button className="btn-sm" disabled={busy || load.phase === 'loading'}
          onClick={() => { setActionError(''); setAttempt(value => value + 1); }}>Refresh</button>
      </div>
      {actionError && <p className="knowledge-gaps-error" role="alert">Couldn't update the report: {actionError}</p>}
      {load.phase === 'loading' && <p role="status">Loading knowledge gaps…</p>}
      {load.phase === 'error' && <p className="knowledge-gaps-error" role="alert">Couldn't load knowledge gaps: {load.message} Use Refresh to try again.</p>}
      {load.phase === 'ready' && (visible.length
        ? <ul className="knowledge-gaps-list">{visible.map(gap => <KnowledgeGapCard key={gap.id} gap={gap} busy={busy} onAction={onAction} />)}</ul>
        : <p role="status">{filter === 'all' ? 'No knowledge gaps have been reported.' : `No ${filter} knowledge gaps.`}</p>)}
    </main>
  );
}

window.KnowledgeGapsScreen = KnowledgeGapsScreen;
