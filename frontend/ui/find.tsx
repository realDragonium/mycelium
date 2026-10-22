// Find: semantic, grep and survey over statements, run server-side, plus the
// entities whose names match. Shows real scores and never hides the tail.
import { useCallback, type ReactNode } from 'react';
import { EditableStatementText, EmptyState, I, KindTag, LoadError, PageHeader, ScoreMeter, type IconName } from './lib';
import { Link, useRouter } from './router';
import { findStatements, isAuthError, searchEntities, type EntityHit, type FindMode, type FindRow } from './api';
import { substrate } from './data';
import { useAsync } from './use-async';

const MODES: Record<FindMode, { name: string; icon: IconName; desc: string; note: ReactNode }> = {
  semantic: { name: 'Semantic', icon: 'semantic', desc: 'meaning · fuzzy',
    note: <>Vector search over embeddings, ranked by <b>meaning</b> rather than wording. Near-misses are expected.</> },
  grep: { name: 'Grep', icon: 'grep', desc: 'literal · alias-aware',
    note: <>Literal substring match, <b>alias-aware</b>: a hit on any name routes through to the statements that mention it.</> },
  survey: { name: 'Survey', icon: 'survey', desc: 'breadth · no floor',
    note: <>Splits the query into parts and merges the results. <b>No score floor</b>: the long tail rides along and you judge it.</> },
};

export function FindLanes({ mode, onMode }: { mode: FindMode; onMode: (mode: FindMode) => void }) {
  return (
    <div className="find-lanes" role="group" aria-label="Find mode">
      <span className="ll">mode</span>
      {(Object.keys(MODES) as FindMode[]).map(k => {
        const m = MODES[k];
        return (
          <button key={k} className={`lane${mode === k ? ' on' : ''}`} aria-pressed={mode === k} onClick={() => onMode(k)}>
            {I[m.icon]({ className: 'lane-glyph' })}
            <span className="lane-name">{m.name}</span>
            <span className="lane-desc">{m.desc}</span>
          </button>
        );
      })}
    </div>
  );
}

function ResultRow({ r, rank, mode, query, tail }: { r: FindRow; rank: number; mode: FindMode; query: string; tail?: boolean }) {
  const { go } = useRouter();
  const grep = mode === 'grep';
  const statement = substrate.index.statements[r.id] || { id: r.id, text: r.text, mentions: [] };
  return (
    <div className={`res${tail ? ' tail' : ''}`} onClick={() => go({ view: 'statement', id: r.id })}>
      <div className="r-rank">{String(rank).padStart(2, '0')}</div>
      <div className="r-kind"><KindTag kind={r.kind} /></div>
      <div className="r-body">
        <div className="r-id">
          <Link to={{ view: 'statement', id: r.id }}>{r.id}</Link>
          {grep && (r.via === 'mention' || r.via === 'both') && <> · via alias</>}
        </div>
        <EditableStatementText statement={statement} className="r-text" highlightQuery={grep ? query : ''} compact />
      </div>
      <div className="r-right">
        {/* Grep has no relevance score; show how it matched instead. */}
        {grep
          ? <span className="r-sub" title={`matched via ${r.via || 'text'}`}>{r.via || 'text'}{r.occurrences > 0 && <> · {r.occurrences}×</>}</span>
          : <ScoreMeter score={r.score} />}
      </div>
    </div>
  );
}

// Entities whose names match: semantically for semantic and survey, as a
// literal name match for grep.
function grepEntities(query: string): EntityHit[] {
  const q = query.trim().toLowerCase();
  const idx = substrate.index;
  const hits: EntityHit[] = [];
  for (const e of substrate.data.entities) {
    const names = [e.name, ...(idx.namesByEntity[e.id] || []).map(n => n.text)];
    const matched = names.find(n => n.toLowerCase().includes(q));
    if (matched) hits.push({ id: e.id, name: e.name, matched_name: matched, description: e.description, score: null });
  }
  return hits.slice(0, 8);
}

function EntityStrip({ hits }: { hits: EntityHit[] }) {
  if (!hits.length) return null;
  return (
    <section className="entity-strip" aria-label="Matching entities">
      <span className="ll">entities</span>
      {hits.map(h => (
        <Link key={h.id} to={{ view: 'entity', id: h.id }} className="echip" title={h.description}>
          {h.name}{h.matched_name !== h.name && <span className="echip-alias"> · “{h.matched_name}”</span>}
        </Link>
      ))}
    </section>
  );
}

export function FindResults({ query, mode }: { query: string; mode: FindMode }) {
  const { go } = useRouter();
  const m = MODES[mode];
  const q = query.trim();
  const load = useCallback(async (signal: AbortSignal) => {
    if (!q) return { rows: [], entities: [] };
    const [rows, entities] = await Promise.all([
      findStatements(mode, q, signal),
      mode === 'grep' ? grepEntities(q) : searchEntities(q, signal).catch((): EntityHit[] => []),
    ]);
    return { rows, entities };
  }, [mode, q]);
  const { state, reload } = useAsync(load);

  if (!q) {
    return <main className="page narrow"><EmptyState title="Nothing to find yet" blurb="Type a query and pick a mode. Find returns raw matches with scores; you judge relevance." /></main>;
  }

  const rows = state.status === 'ready' ? state.data.rows : [];
  // Survey has no score floor: split the strong head from the faded tail.
  const head = mode === 'survey' ? rows.filter(r => (r.score ?? 0) >= 0.4) : rows;
  const tail = mode === 'survey' ? rows.filter(r => (r.score ?? 0) < 0.4) : [];

  return (
    <main className="page narrow">
      <PageHeader eyebrow="Find" title={<span className="mono">{query}</span>}
        actions={<span className="count-pill">{state.status === 'loading' ? 'searching…' : `${rows.length} result${rows.length === 1 ? '' : 's'}`}</span>} />
      <FindLanes mode={mode} onMode={k => go({ view: 'find', query, mode: k })} />
      <div className="find-note"><I.find className="fn-icon" width="15" height="15" /><div>{m.note}</div></div>

      {state.status === 'loading' ? (
        <div className="results"><div className="res"><div className="r-rank">··</div><div className="r-body"><div className="r-text muted">searching…</div></div></div></div>
      ) : state.status === 'error' ? (
        isAuthError(state.error)
          ? <EmptyState title="Sign in to search" blurb="Find needs an authenticated session." />
          : <LoadError error={state.error} what="results" onRetry={reload} />
      ) : (
        <>
          <EntityStrip hits={state.data.entities} />
          {rows.length === 0 ? (
            <EmptyState
              title={mode === 'grep' ? <>No literal match for “{query}”</> : <>No matches for “{query}”</>}
              blurb={mode === 'grep' ? 'Grep is exact. Try Semantic for meaning-based recall, or check the wording.' : 'An empty result is a signal: the knowledge base may not cover this yet.'} />
          ) : (
            <div className="results reveal">
              {head.map((r, i) => <ResultRow key={r.id} r={r} rank={i + 1} mode={mode} query={query} />)}
              {tail.length > 0 && <>
                <div className="tail-divider">long tail · {tail.length} weak match{tail.length === 1 ? '' : 'es'} · shown, not hidden</div>
                {tail.map((r, i) => <ResultRow key={r.id} r={r} rank={head.length + i + 1} mode={mode} query={query} tail />)}
              </>}
            </div>
          )}
        </>
      )}
    </main>
  );
}
