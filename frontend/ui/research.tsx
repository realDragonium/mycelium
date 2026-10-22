// Research: a topic plus a configured repository becomes a server-side run
// that can hand back a draft.
import { useCallback, useEffect, useState } from 'react';
import { EmptyState, I, LoadError, PageHeader, relTime } from './lib';
import { Link } from './router';
import { errorMessage, getReviewMode, HttpError, research, type ResearchRun } from './api';
import { draftFate } from './ingest';
import { useAsync, dataOf } from './use-async';

const ACTIVE = new Set(['queued', 'running']);

export function ResearchSurface() {
  const [topic, setTopic] = useState('');
  const [picked, setPicked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const sources = useAsync(useCallback(() => research.sources(), []));
  const runs = useAsync(useCallback(() => research.list(), []));
  const mode = useAsync(getReviewMode).state;
  const reviewMode = mode.status === 'ready' ? mode.data : null;
  const runList = dataOf(runs.state) || [];
  const sourceList = dataOf(sources.state) || [];
  // One configured source is picked for you.
  const source = picked ?? (sourceList.length === 1 ? sourceList[0].name : '');

  const anyActive = runList.some(r => ACTIVE.has(r.status));
  const { reload } = runs;
  useEffect(() => {
    if (!anyActive) return;
    const t = setInterval(reload, 2500);
    return () => clearInterval(t);
  }, [anyActive, reload]);

  const start = async () => {
    const q = topic.trim();
    if (!q || !source || busy) return;
    setBusy(true); setErr(null);
    try {
      await research.start(q, source);
      setTopic(''); reload();
    } catch (e) {
      setErr(e instanceof HttpError && e.status === 403 ? 'You need drafter access to start research runs.' : errorMessage(e, 'Research failed.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="page narrow"><div className="ingest-stage">
      <PageHeader eyebrow="Add knowledge" title={<>Research a topic. Let the <em className="write">librarian</em> draft what it finds.</>}
        blurb={<>Pick a configured repository, describe the question, and start a server-side run that reads the code. {draftFate(reviewMode, 'run’s draft')}</>} />

      <div className="src-type-row" role="group" aria-label="Research source">
        <span className="ll">source</span>
        {sourceList.map(s => (
          <button key={s.name} className={`src-chip${source === s.name ? ' on' : ''}`} aria-pressed={source === s.name} onClick={() => setPicked(s.name)}>
            <I.find className="sc-glyph" />{s.name}
          </button>
        ))}
        {sources.state.status === 'ready' && !sourceList.length && (
          <span className="hint">No repositories configured. Add one under <Link to={{ view: 'settings', section: 'research' }}>Settings → Research sources</Link>.</span>
        )}
      </div>
      {sources.state.status === 'error' && <LoadError error={sources.state.error} what="research sources" onRetry={sources.reload} />}

      <div className="ingest-field">
        <textarea value={topic} onChange={e => setTopic(e.target.value)} spellCheck={false} aria-label="Research topic"
          placeholder={'What should be researched? For example: "how invite reminders are scheduled"'} />
        <div className="ingest-foot">
          <span className="if-meta"><b>{topic.trim() ? topic.trim().split(/\s+/).length : 0}</b> words</span>
          <span className="if-spacer" />
          <button className="btn write" disabled={!topic.trim() || !source || busy} onClick={start}><I.ask width="15" height="15" />{busy ? 'Starting…' : 'Start research'}</button>
        </div>
      </div>
      {err && <p className="form-error" role="alert">{err}</p>}

      <h2 className="section-label spaced">Runs · newest first</h2>
      {runs.state.status === 'error' && <LoadError error={runs.state.error} what="research runs" onRetry={reload} />}
      {runs.state.status === 'ready' && runList.length === 0
        ? <EmptyState title="No research runs yet" blurb="Start a run to fill this list." />
        : <div className="row-list">{runList.map(run => <RunRow key={run.id} run={run} />)}</div>}
    </div></main>
  );
}

function RunRow({ run }: { run: ResearchRun }) {
  const tone = run.status === 'draft_created' ? 'ok' : run.status === 'failed' ? 'bad' : ACTIVE.has(run.status) ? 'live' : 'idle';
  return (
    <div className="list-row static">
      <span className={`dot ${tone}`} />
      <div className="lr-body">
        <div className="lr-title">{run.topic || 'Untitled research run'}</div>
        <div className="lr-meta">
          <span className="mono">{run.id}</span><span>·</span><span>{run.source || 'source'}</span><span>·</span><span>{relTime(run.created_at)}</span>
          {(run.status === 'failed' || run.status === 'nothing_found') && run.error && <><span>·</span><span className="warn-text">{run.error}</span></>}
        </div>
      </div>
      <span className={`status-badge ${tone}`}>{run.status.replace('_', ' ')}</span>
      {run.status === 'draft_created' && run.draft_id
        ? <Link to={{ view: 'draft', id: run.draft_id }} className="btn sm"><I.prov width="13" height="13" />View draft</Link>
        : <span className="lr-time">{run.finished_at ? relTime(run.finished_at) : ''}</span>}
    </div>
  );
}
