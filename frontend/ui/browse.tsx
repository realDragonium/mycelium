// Browse: every statement, entity and name as a table.
import { useMemo, useState } from 'react';
import { KindTag, PageHeader } from './lib';
import { Link, useRouter } from './router';
import { substrate } from './data';

type Tab = 'statement' | 'entity' | 'name';
const TABS: { id: Tab; label: string }[] = [
  { id: 'statement', label: 'Statements' }, { id: 'entity', label: 'Entities' }, { id: 'name', label: 'Names' },
];

function StatementsTable() {
  const { go } = useRouter();
  const { data, index: idx } = substrate;
  const kindCounts = useMemo(() => {
    const m: Record<string, number> = {};
    data.statements.forEach(s => { m[s.kind] = (m[s.kind] || 0) + 1; });
    return m;
  }, [data]);
  const kinds = Object.keys(kindCounts).sort();
  // Kinds the reader has hidden; a kind seen for the first time shows.
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const rows = data.statements.filter(s => !hidden.has(s.kind));
  const toggle = (k: string) => setHidden(prev => { const next = new Set(prev); if (next.has(k)) next.delete(k); else next.add(k); return next; });
  return <>
    <div className="filter-row compact" role="group" aria-label="Statement kinds">
      <span className="ll">kinds</span>
      {kinds.map(k => <button key={k} className={`fchip${hidden.has(k) ? '' : ' on'}`} aria-pressed={!hidden.has(k)} onClick={() => toggle(k)}>{k}<span className="fc-ct">{kindCounts[k]}</span></button>)}
    </div>
    <table className="tbl">
      <thead><tr><th className="num">#</th><th>kind</th><th>statement</th><th className="num">out</th><th className="num">in</th><th className="num">mentions</th></tr></thead>
      <tbody>
        {rows.map((s, i) => (
          <tr key={s.id} onClick={() => go({ view: 'statement', id: s.id })}>
            <td className="num muted">{i + 1}</td>
            <td><KindTag kind={s.kind} /></td>
            <td><Link to={{ view: 'statement', id: s.id }} className="row-title">{s.title}</Link><div className="row-id">{s.id}</div></td>
            <td className="num">{(idx.outgoing[s.id] || []).length}</td>
            <td className="num">{(idx.incoming[s.id] || []).length}</td>
            <td className="num">{s.mentions.length}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </>;
}

function EntitiesTable() {
  const { go } = useRouter();
  const { data, index: idx } = substrate;
  return (
    <table className="tbl">
      <thead><tr><th className="num">#</th><th>entity</th><th>description</th><th className="num">aliases</th><th className="num">mentioned</th></tr></thead>
      <tbody>
        {data.entities.map((e, i) => (
          <tr key={e.id} onClick={() => go({ view: 'entity', id: e.id })}>
            <td className="num muted">{i + 1}</td>
            <td><Link to={{ view: 'entity', id: e.id }} className="row-title">{e.name}</Link><div className="row-id">{e.id}</div></td>
            <td className="muted">{e.description}</td>
            <td className="num">{(idx.namesByEntity[e.id] || []).length}</td>
            <td className="num">{(idx.mentionsByEntity[e.id] || []).length}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function NamesTable() {
  const { go } = useRouter();
  const { data, index: idx } = substrate;
  return (
    <table className="tbl">
      <thead><tr><th className="num">#</th><th>name</th><th>resolves to</th></tr></thead>
      <tbody>
        {data.names.map((n, i) => {
          const e = idx.entities[n.entity];
          return (
            <tr key={n.id} onClick={() => go({ view: 'entity', id: n.entity })}>
              <td className="num muted">{i + 1}</td>
              <td className="mono">“{n.text}”<div className="row-id">{n.id}</div></td>
              <td>{e ? <Link to={{ view: 'entity', id: e.id }} className="row-title">{e.name}</Link> : <span className="muted">{n.entity}</span>}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function BrowseScreen() {
  const [tab, setTab] = useState<Tab>('statement');
  const { data } = substrate;
  const counts: Record<Tab, number> = { statement: data.statements.length, entity: data.entities.length, name: data.names.length };
  return (
    <main className="page">
      <PageHeader eyebrow="Explore" title="Browse" blurb="Every record in the knowledge base. Use Find for search, or the graphs to see how records connect." />
      <div className="tabs" role="tablist">
        {TABS.map(t => <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'on' : ''} onClick={() => setTab(t.id)}>{t.label}<span className="ct">{counts[t.id]}</span></button>)}
      </div>
      {tab === 'statement' ? <StatementsTable /> : tab === 'entity' ? <EntitiesTable /> : <NamesTable />}
    </main>
  );
}
