// Knowledge health: what needs a curator, counted on the server, with the
// list behind each count and an AI pass that proposes links for statements
// nothing reaches.
import { useCallback, useEffect, useRef, useState } from 'react';
import { draftFate } from './ingest';
import { EmptyState, KindTag, LoadError, Loading, Notice, PageHeader, useMe } from './lib';
import { Link, type Route } from './router';
import {
  errorMessage, getReviewMode, isStatementFilter, knowledgeHealth,
  type ConnectLimits, type ConnectResult, type EntityFilter, type HealthCounts, type HealthEntity, type HealthList,
  type HealthStatement, type StatementFilter,
} from './api';
import { dataOf, useAsync } from './use-async';

const LISTS: Record<HealthList, { title: string; blurb: string; empty: string }> = {
  isolated: { title: 'Isolated statements', blurb: 'No link leads to or from these statements or holds only when they do, so Ask, documentation and the planner only reach them by search.', empty: 'Every statement has a link.' },
  unmentioned: { title: 'Statements naming no concept', blurb: 'No concept name or alias appears in these statements, so nothing about a concept leads to them.', empty: 'Every statement names a concept.' },
  unlabelled: { title: 'Statements without an audience label', blurb: 'Only internal audiences see these statements until they are labelled. A failed labelling attempt shows its error.', empty: 'Every statement has an audience label.' },
  undescribed: { title: 'Concepts without a description', blurb: 'Readers and the AI see only the name of these concepts.', empty: 'Every concept has a description.' },
  unused: { title: 'Concepts no statement mentions', blurb: 'No statement uses any name of these concepts.', empty: 'Every concept is mentioned.' },
};

interface Tile { n: number; label: string; sub: string; to: Route; tone?: 'warn' | 'write' }

function tiles(c: HealthCounts): Tile[] {
  const list = (l: HealthList): Route => ({ view: 'health', list: l });
  const of = (n: number, total: number) => total ? `${Math.round(n / total * 100)}% of ${total}` : 'none yet';
  return [
    { n: c.isolated, label: 'isolated statements', sub: `${of(c.isolated, c.statements)}, no links or conditions`, to: list('isolated'), tone: 'warn' },
    { n: c.unmentioned, label: 'statements naming no concept', sub: of(c.unmentioned, c.statements), to: list('unmentioned'), tone: 'warn' },
    { n: c.undescribed, label: 'concepts without a description', sub: of(c.undescribed, c.entities), to: list('undescribed') },
    { n: c.unused, label: 'concepts no statement mentions', sub: of(c.unused, c.entities), to: list('unused') },
    { n: c.unlabelled, label: 'statements without an audience label', sub: c.labelling_failed ? `${c.labelling_failed} failed to label` : 'none failed', to: list('unlabelled') },
    { n: c.open_gaps, label: 'open knowledge gaps', sub: 'reported by agents and people', to: { view: 'gaps' }, tone: 'warn' },
    { n: c.out_of_date_documents, label: 'out-of-date documents', sub: 'a statement they cite has changed', to: { view: 'documentation' } },
    { n: c.pending_drafts, label: 'pending drafts', sub: 'open with their authors or awaiting a decision', to: { view: 'drafts' }, tone: 'write' },
  ];
}

const usd = (n: number) => `$${n < 0.1 ? n.toFixed(3) : n.toFixed(2)}`;

type Run =
  | { phase: 'idle' }
  | { phase: 'running'; count: number; startedAt: number }
  | { phase: 'done'; result: ConnectResult }
  | { phase: 'error'; message: string };

// One connect run at a time per screen; a response after leaving is dropped.
function useConnect(onDone: () => void) {
  const [run, setRun] = useState<Run>({ phase: 'idle' });
  const live = useRef(0);
  useEffect(() => () => { live.current++; }, []);
  const start = useCallback(async (ids: string[]) => {
    const mine = ++live.current;
    setRun({ phase: 'running', count: ids.length, startedAt: Date.now() });
    try {
      const result = await knowledgeHealth.connect(ids);
      if (mine === live.current) { setRun({ phase: 'done', result }); onDone(); }
      return true;
    } catch (e) {
      if (mine === live.current) setRun({ phase: 'error', message: errorMessage(e, 'The connect run failed.') });
      return false;
    }
  }, [onDone]);
  return { run, start };
}

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(t); }, []);
  return <>{Math.round((now - since) / 1000)}s</>;
}

function RunStatus({ run }: { run: Run }) {
  if (run.phase === 'idle') return null;
  if (run.phase === 'running') return <Notice>Looking for connections for {run.count} statement{run.count === 1 ? '' : 's'}… <Elapsed since={run.startedAt} />. This takes a minute or two; the draft will be under <Link to={{ view: 'drafts' }}>Drafts</Link>.</Notice>;
  if (run.phase === 'error') return <Notice tone="error">{run.message}</Notice>;
  const { result } = run;
  const cost = result.cost_usd === null ? 'cost unknown for this model' : `cost ${usd(result.cost_usd)}`;
  const gaps = result.gaps_filed?.length || 0;
  const filed = gaps ? <>; asked for {gaps} statement{gaps === 1 ? '' : 's'} to be rephrased in <Link to={{ view: 'gaps' }}>Knowledge gaps</Link></> : null;
  if (result.outcome === 'nothing_to_ingest') return <Notice tone="warn">No connections proposed ({result.reason || 'nothing found'}); {cost}{filed}.</Notice>;
  const flagged = result.flagged?.length || 0;
  return (
    <Notice tone="success">
      <span>
        Proposed {result.ops?.length || 0} change{result.ops?.length === 1 ? '' : 's'} in <Link to={{ view: 'draft', id: result.draft_id }}>{result.draft_id}</Link>
        {result.alias_draft_id && result.alias_draft_id !== result.draft_id && <>, aliases in <Link to={{ view: 'draft', id: result.alias_draft_id }}>{result.alias_draft_id}</Link></>}
        {result.submitted_for_review ? ', submitted to the AI reviewer' : ''}; {cost}{flagged ? `; ${flagged} note${flagged === 1 ? '' : 's'} for the reviewer` : ''}{filed}.
      </span>
    </Notice>
  );
}

function ConnectPanel({ limits, onDone }: { limits: ConnectLimits; onDone: () => void }) {
  const [scope, setScope] = useState<StatementFilter>('isolated');
  const [count, setCount] = useState(limits.batch_size);
  const [empty, setEmpty] = useState(false);
  const mode = useAsync(getReviewMode).state;
  const { run, start } = useConnect(onDone);
  const n = Math.max(1, Math.min(limits.batch_size, count || 1));

  const pick = (next: StatementFilter) => { setScope(next); setEmpty(false); };
  const next = async () => {
    setEmpty(false);
    const page = await knowledgeHealth.statements(scope, { limit: n, toConnect: true });
    if (!page.items.length) { setEmpty(true); return; }
    await start(page.items.map(s => s.id));
  };

  return (
    <section className="card health-connect" aria-labelledby="health-connect">
      <h2 id="health-connect">Connect statements with AI</h2>
      <p>
        Proposes links to existing statements and concept mentions for statements that have none. It never rewrites or deletes a statement.
        {' '}{draftFate(mode.status === 'ready' ? mode.data : null, 'proposal')}
      </p>
      <div className="filter-row compact" role="group" aria-label="Which statements">
        {(['isolated', 'unmentioned'] as const).map(s => (
          <button key={s} className={`fchip${scope === s ? ' on' : ''}`} aria-pressed={scope === s} onClick={() => pick(s)}>{LISTS[s].title}</button>
        ))}
      </div>
      <div className="row gap-sm health-connect-run">
        <label className="health-count">Next <input type="number" min={1} max={limits.batch_size} value={count} onChange={e => setCount(Number(e.target.value))} aria-label="Statements per run" /></label>
        <button className="btn write" disabled={run.phase === 'running'} onClick={() => { void next(); }}>Connect next {n}</button>
      </div>
      <p className="hint">
        {limits.model} · at most {limits.batch_size} statements a run · {limits.priced ? `stops at ${usd(limits.max_cost_usd)} a run` : 'no known price for this model, so cost is not shown and the spending cap cannot apply'}.
        {' '}Statements in a pending draft, and those it already looked at, are skipped until they or the statements around them change. <Link to={{ view: 'settings', section: 'limits' }}>Limits</Link> · <Link to={{ view: 'settings', section: 'models' }}>Model</Link>
      </p>
      {empty && <Notice>No {scope === 'isolated' ? 'isolated statements' : 'statements naming no concept'} left that the AI has not already looked at.</Notice>}
      <RunStatus run={run} />
    </section>
  );
}

function StatementRows({ which, limits, canConnect, onDone }: { which: StatementFilter; limits: ConnectLimits | null; canConnect: boolean; onDone: () => void }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const { state, reload, update } = useAsync(useCallback(() => knowledgeHealth.statements(which), [which]));
  const page = dataOf(state);
  const rows: HealthStatement[] = page?.items ?? [];
  const done = useCallback(() => { setSelected(new Set()); onDone(); reload(); }, [onDone, reload]);
  const { run, start } = useConnect(done);
  const [moreError, setMoreError] = useState('');

  const more = async () => {
    setMoreError('');
    try {
      const next = await knowledgeHealth.statements(which, { after: page?.next_after });
      update(p => ({ items: [...p.items, ...next.items], next_after: next.next_after }));
    } catch (e) { setMoreError(errorMessage(e)); }
  };
  const toggle = (id: string) => setSelected(s => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const selectable = canConnect && !!limits && which !== 'unlabelled';
  const tooMany = !!limits && selected.size > limits.batch_size;

  if (state.status === 'loading' && !page) return <Loading what="statements" />;
  if (state.status === 'error') return <LoadError error={state.error} what="statements" onRetry={reload} />;
  if (!rows.length) return <EmptyState title={LISTS[which].empty} />;
  return <>
    {selectable && <div className="row gap-sm health-select">
      <button className="btn write sm" disabled={!selected.size || tooMany || run.phase === 'running'} onClick={() => { void start([...selected]); }}>Connect selected ({selected.size})</button>
      {tooMany && <span className="hint">At most {limits?.batch_size} a run.</span>}
    </div>}
    {selectable && <RunStatus run={run} />}
    <ul className="card-list health-list">
      {rows.map(s => (
        <li key={s.id} className="card health-row">
          {selectable && <input type="checkbox" checked={selected.has(s.id)} onChange={() => toggle(s.id)} aria-label={`Select ${s.id}`} />}
          <div className="health-row-body">
            <Link to={{ view: 'statement', id: s.id }}><KindTag kind={s.kind} /> {s.text}</Link>
            <div className="meta-row">
              <span>{s.links} link{s.links === 1 ? '' : 's'}</span>
              <span>{s.mentions.length ? `names ${s.mentions.join(', ')}` : 'names no concept'}</span>
              {s.label_error && <span className="health-error">labelling failed: {s.label_error}</span>}
              {s.in_pending_draft && <span className="status-badge open">in a pending draft</span>}
              {s.settled_at && <span title={`Looked at ${s.settled_at}; offered again once it or the statements around it change`}>already looked at by the AI</span>}
              <span className="mono">{s.id}</span>
            </div>
          </div>
        </li>
      ))}
    </ul>
    {moreError && <Notice tone="error">Could not load more: {moreError}</Notice>}
    {page?.next_after && <button className="btn sm" onClick={() => { void more(); }}>Load more</button>}
  </>;
}

function EntityRows({ which }: { which: EntityFilter }) {
  const { state, reload, update } = useAsync(useCallback(() => knowledgeHealth.entities(which), [which]));
  const page = dataOf(state);
  const rows: HealthEntity[] = page?.items ?? [];
  const [moreError, setMoreError] = useState('');
  const more = async () => {
    setMoreError('');
    try {
      const next = await knowledgeHealth.entities(which, page?.next_after);
      update(p => ({ items: [...p.items, ...next.items], next_after: next.next_after }));
    } catch (e) { setMoreError(errorMessage(e)); }
  };

  if (state.status === 'loading' && !page) return <Loading what="concepts" />;
  if (state.status === 'error') return <LoadError error={state.error} what="concepts" onRetry={reload} />;
  if (!rows.length) return <EmptyState title={LISTS[which].empty} />;
  return <>
    <ul className="card-list health-list">
      {rows.map(e => (
        <li key={e.id} className="card health-row">
          <div className="health-row-body">
            <Link to={{ view: 'entity', id: e.id }}>{e.name || e.id}</Link>
            <div className="meta-row">{e.description ? <span>{e.description}</span> : <span>no description</span>}<span className="mono">{e.id}</span></div>
          </div>
        </li>
      ))}
    </ul>
    {moreError && <Notice tone="error">Could not load more: {moreError}</Notice>}
    {page?.next_after && <button className="btn sm" onClick={() => { void more(); }}>Load more</button>}
  </>;
}

export function KnowledgeHealthScreen({ list }: { list: HealthList | null }) {
  const me = useMe();
  const { state, reload } = useAsync(knowledgeHealth.view);
  const view = dataOf(state);
  const canConnect = !!me && me.role !== 'reader';

  if (list) {
    const info = LISTS[list];
    return (
      <main className="page narrow">
        <PageHeader eyebrow={<Link to={{ view: 'health', list: null }}>Knowledge health</Link>} title={info.title} blurb={info.blurb} />
        {isStatementFilter(list)
          ? <StatementRows key={list} which={list} limits={view?.connect ?? null} canConnect={canConnect} onDone={reload} />
          : <EntityRows key={list} which={list} />}
      </main>
    );
  }
  return (
    <main className="page">
      <PageHeader eyebrow="Curate" title="Knowledge health"
        blurb="Knowledge nothing leads to is hard for search, Ask, documentation and planning to use. Each count opens the list behind it."
        actions={<button className="btn sm" disabled={state.status === 'loading'} onClick={reload}>Refresh</button>} />
      {state.status === 'loading' && !view && <Loading what="knowledge health" />}
      {state.status === 'error' && <LoadError error={state.error} what="knowledge health" onRetry={reload} />}
      {view && <>
        <div className="attention-grid health-grid">
          {tiles(view.counts).map(t => (
            <Link key={t.label} to={t.to} className={`attention-card${t.n && t.tone ? ` ${t.tone}` : ''}`}>
              <span className="ac-n">{t.n}</span><span className="ac-l">{t.label}</span><span className="ac-sub">{t.sub}</span>
            </Link>
          ))}
        </div>
        {canConnect && (view.connect
          ? <ConnectPanel limits={view.connect} onDone={reload} />
          : <Notice tone="warn">Connecting statements is unavailable: {view.connect_error}</Notice>)}
      </>}
    </main>
  );
}
