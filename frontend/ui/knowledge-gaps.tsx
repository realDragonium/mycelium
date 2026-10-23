// Knowledge gaps: reports filed by agents (report_knowledge_gap) and people
// (Ask's Report a gap). Resolve, dismiss or reopen them.
import { useCallback, useState } from 'react';
import { EmptyState, LoadError, Loading, Notice, PageHeader, formatDate } from './lib';
import { Link } from './router';
import { errorMessage, knowledgeGaps, type GapAction, type GapStatus, type KnowledgeGap } from './api';
import { dataOf, useAsync } from './use-async';

const FILTERS: ReadonlyArray<{ id: GapStatus | 'all'; label: string }> = [
  { id: 'open', label: 'Open' },
  { id: 'resolved', label: 'Resolved' },
  { id: 'dismissed', label: 'Dismissed' },
  { id: 'all', label: 'All' },
];

function GapCard({ gap, busy, onAction }: { gap: KnowledgeGap; busy: boolean; onAction: (id: string, action: GapAction) => void }) {
  const changedAt = gap.resolved_at || gap.dismissed_at;
  return (
    <li className={`card gap-card ${gap.status}`}>
      <div className="gap-body">
        <p>{gap.text}</p>
        <div className="meta-row">
          <span>Reported <time dateTime={gap.created_at}>{formatDate(gap.created_at)}</time>{gap.created_by ? ` by ${gap.created_by.slice(0, 8)}` : ''}</span>
          {changedAt && <span>{gap.status} <time dateTime={changedAt}>{formatDate(changedAt)}</time></span>}
          <span className="mono">{gap.id}</span>
          {gap.statement_id && <Link to={{ view: 'statement', id: gap.statement_id }}>Statement {gap.statement_id.slice(0, 12)}</Link>}
          {gap.draft_id && <Link to={{ view: 'draft', id: gap.draft_id }}>Draft {gap.draft_id.slice(0, 12)}</Link>}
          {gap.document_id && <Link to={{ view: 'documentation' }} title={gap.document_id}>Document {gap.document_id.slice(0, 12)}</Link>}
        </div>
      </div>
      <div className="gap-controls">
        <span className={`status-badge ${gap.status === 'open' ? 'warn' : gap.status === 'resolved' ? 'ok' : 'idle'}`}>{gap.status}</span>
        <div className="row gap-sm">
          {gap.status === 'open' ? <>
            <button className="btn sm" disabled={busy} onClick={() => onAction(gap.id, 'resolve')} title="The gap was addressed.">Resolve</button>
            <button className="btn sm" disabled={busy} onClick={() => onAction(gap.id, 'dismiss')} title="Not a gap, or not worth fixing.">Dismiss</button>
            <Link to={{ view: 'research', topic: gap.text }} className="btn sm" title="Open Research with this report as the topic.">Research</Link>
          </> : <button className="btn sm" disabled={busy} onClick={() => onAction(gap.id, 'reopen')}>Reopen</button>}
        </div>
      </div>
    </li>
  );
}

export function KnowledgeGapsScreen() {
  const [filter, setFilter] = useState<GapStatus | 'all'>('open');
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const { state, reload, update } = useAsync(useCallback(() => knowledgeGaps.list(), []));
  const gaps = dataOf(state);

  const onAction = async (id: string, action: GapAction) => {
    setBusy(true); setActionError('');
    try {
      // The saved row replaces the old one, so a failed re-read cannot misreport the action.
      const saved = await knowledgeGaps.update(id, action);
      update(list => list.map(g => g.id === id ? saved : g));
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const visible = (gaps || []).filter(g => filter === 'all' || g.status === filter);
  return (
    <main className="page narrow">
      <PageHeader eyebrow="Curate" title="Knowledge gaps"
        blurb="Questions the knowledge base could not answer, contradictions and unclear areas, reported by agents and people. Resolve a report once it is addressed, dismiss it if no action is needed, or reopen it later."
        actions={<button className="btn sm" disabled={busy || state.status === 'loading'} onClick={() => { setActionError(''); reload(); }}>Refresh</button>} />
      <div className="filter-row" role="group" aria-label="Filter knowledge gaps">
        {FILTERS.map(item => (
          <button key={item.id} className={`fchip${filter === item.id ? ' on' : ''}`} aria-pressed={filter === item.id} onClick={() => setFilter(item.id)}>
            {item.label}{gaps && <span className="fc-ct">{gaps.filter(g => item.id === 'all' || g.status === item.id).length}</span>}
          </button>
        ))}
      </div>
      {actionError && <Notice tone="error">Could not update the report: {actionError}</Notice>}
      {state.status === 'loading' && !gaps && <Loading what="knowledge gaps" />}
      {state.status === 'error' && <LoadError error={state.error} what="knowledge gaps" onRetry={reload} />}
      {gaps && (visible.length
        ? <ul className="card-list">{visible.map(gap => <GapCard key={gap.id} gap={gap} busy={busy} onAction={onAction} />)}</ul>
        : <EmptyState title={filter === 'all' ? 'No knowledge gaps reported' : `No ${filter} knowledge gaps`}
            blurb={filter === 'open' ? 'Nothing on the radar right now.' : undefined} />)}
    </main>
  );
}
