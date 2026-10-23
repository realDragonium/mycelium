// What the two graph views open on. Drawing every record at once is an
// unreadable clump on a real knowledge base, so a graph opens on a picked
// concept's neighbourhood, and the whole substrate only when asked.
import { useCallback, useMemo, useState } from 'react';
import { GraphView } from './graph';
import { LoadError, Loading, PageHeader } from './lib';
import { Link } from './router';
import { loadGraphConcepts, loadNeighbourhood } from './data';
import { useAsync } from './use-async';

type GraphViewName = 'graph' | 'entities';

const SHOWN = 40;

export function GraphPicker({ view }: { view: GraphViewName }) {
  const { state, reload } = useAsync(loadGraphConcepts);
  const [query, setQuery] = useState('');
  const concepts = useMemo(() => {
    if (state.status !== 'ready') return [];
    const all = view === 'entities'
      ? [...state.data.concepts].sort((a, b) => b.links - a.links || b.statements - a.statements)
      : state.data.concepts;
    const q = query.trim().toLowerCase();
    return (q ? all.filter(c => c.name.toLowerCase().includes(q)) : all).slice(0, SHOWN);
  }, [state, view, query]);

  const title = view === 'graph' ? 'Statement graph' : 'Entity map';
  if (state.status === 'error') return <main className="page"><LoadError error={state.error} what="the concepts" onRetry={reload} /></main>;
  if (state.status === 'loading') return <main className="page"><Loading what="the concepts" /></main>;
  const { statements } = state.data;
  return (
    <main className="page narrow">
      <PageHeader
        title={title}
        blurb="Pick a concept to see its neighbourhood."
        actions={<Link to={{ view, focus: null, all: true }} className="btn ghost sm">
          Show everything · {view === 'graph' ? `${statements.toLocaleString()} statements` : `${state.data.concepts.length.toLocaleString()} concepts`}
        </Link>}
      />
      <input className="input" type="search" placeholder="Find a concept" value={query} onChange={e => setQuery(e.target.value)} autoFocus aria-label="Find a concept" />
      <div className="row-list">
        {concepts.map(c => (
          <Link key={c.id} to={{ view, focus: c.id, all: false }} className="list-row concept-row">
            <span className="lr-title">{c.name}</span>
            <span className="lr-meta">{c.statements} statements · {c.links} concept links</span>
          </Link>
        ))}
        {concepts.length === 0 && <p className="muted">No concept matches.</p>}
      </div>
    </main>
  );
}

export function FocusedStatementGraph({ focus }: { focus: string }) {
  const load = useCallback(() => loadNeighbourhood(focus), [focus]);
  const { state, reload } = useAsync(load);
  if (state.status === 'error') return <main className="page"><LoadError error={state.error} what="this neighbourhood" onRetry={reload} /></main>;
  if (state.status === 'loading') return <main className="page"><Loading what="the neighbourhood" /></main>;
  const { data, index } = state.data;
  const record = index.byId[focus];
  const name = record?.kind === 'entity' ? record.name : record?.title;
  return (
    <GraphView
      key={focus}
      data={data}
      index={index}
      focusId={focus}
      layout="spiral"
      scope={<GraphScope view="graph" label={`Around ${name ?? focus}`} />}
    />
  );
}

export function GraphScope({ view, label }: { view: GraphViewName; label: string | null }) {
  return (
    <div className="graph-scope">
      {label
        ? <><span>{label}</span><Link to={{ view, focus: null, all: true }}>Show everything</Link></>
        : <span>Everything</span>}
      <Link to={{ view, focus: null, all: false }}>Pick a concept</Link>
    </div>
  );
}
