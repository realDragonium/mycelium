// Home: the Ask | Find entry point, what the knowledge base holds, and what
// is waiting for a person.
import { useCallback } from 'react';
import { CommandBar } from './command-bar';
import { I, useGoIngest } from './lib';
import { Link } from './router';
import { getJSON, type KnowledgeGap } from './api';
import { asksPerson, type DraftSummary } from './draft-review';
import { substrate } from './data';
import { useAsync } from './use-async';

export function HomeScreen() {
  const data = substrate.data;
  const goIngest = useGoIngest();
  const load = useCallback(() => Promise.all([
    getJSON<{ drafts: DraftSummary[] }>('/api/drafts?status=all'),
    getJSON<{ gaps: KnowledgeGap[] }>('/api/knowledge-gaps?status=open'),
  ]), []);
  const queue = useAsync(load).state;
  const drafts = queue.status === 'ready' ? queue.data[0].drafts : [];
  const submitted = drafts.filter(d => d.status === 'submitted').length;
  const open = drafts.filter(d => d.status === 'open').length;
  const questions = drafts.filter(d => d.status === 'submitted' && asksPerson(d.review_assessment)).length;
  const gaps = queue.status === 'ready' ? queue.data[1].gaps.length : 0;

  const stats: [number, string][] = [
    [data.statements.length, 'statements'], [data.entities.length, 'entities'], [data.names.length, 'names'],
    [data.links.length, 'links'], [(data.entity_links || []).length, 'entity links'],
  ];

  return (
    <main className="page home">
      <div className="home-hero">
        <div className="eyebrow">Mycelium · knowledge base</div>
        <h1 className="home-title">Interrogate a substrate<br />built to be <em>read by machines</em>.</h1>
        <p className="home-blurb">
          Knowledge enters by <b>ingest</b> and <b>research</b>, and waits as a draft until someone approves it.
          Read it back two ways: <b>Ask</b> for a reasoned answer with its gaps and provenance, or <b>Find</b> for raw, scored matches you judge.
        </p>
      </div>

      <div className="home-cmd"><CommandBar hero /></div>

      <div className="tier-cards">
        <div className="tier-card ask">
          <div className="tc-head"><span className="tc-dot" /><span className="tc-name">Ask</span><span className="tc-kind">agentic · slow</span></div>
          <p>A reasoning loop returns one answer with confidence, the interpretation it used, explicit gaps, provenance and a trace.</p>
        </div>
        <div className="tier-card find">
          <div className="tc-head"><span className="tc-dot" /><span className="tc-name">Find</span><span className="tc-kind">deterministic · fast</span></div>
          <p>Semantic, grep and survey return raw statements with relevance scores. Nothing is hidden; the long tail is shown, faded.</p>
        </div>
      </div>

      <section className="home-section" aria-labelledby="home-attention">
        <h2 id="home-attention" className="section-label">Waiting for you</h2>
        <div className="attention-grid">
          {questions > 0 && <Link to={{ view: 'drafts' }} className="attention-card asks">
            <span className="ac-n">{questions}</span>
            <span className="ac-l">reviewer question{questions === 1 ? '' : 's'} for you</span>
            <span className="ac-sub">the AI reviewer is waiting on a curator's answer</span>
          </Link>}
          <Link to={{ view: 'drafts' }} className="attention-card write">
            <span className="ac-n">{submitted}</span>
            <span className="ac-l">draft{submitted === 1 ? '' : 's'} awaiting a decision</span>
            <span className="ac-sub">{open} still open with their authors</span>
          </Link>
          <Link to={{ view: 'gaps' }} className="attention-card warn">
            <span className="ac-n">{gaps}</span>
            <span className="ac-l">open knowledge gap{gaps === 1 ? '' : 's'}</span>
            <span className="ac-sub">reported by agents and people</span>
          </Link>
          <button className="attention-card ingest" onClick={goIngest}>
            <span className="ac-icon"><I.ingest width="20" height="20" /></span>
            <span className="ac-l">Ingest raw text</span>
            <span className="ac-sub">Paste a doc or transcript; you review the draft before anything is written.</span>
          </button>
        </div>
      </section>

      <section className="home-section" aria-labelledby="home-holds">
        <h2 id="home-holds" className="section-label">What it holds</h2>
        <Link to={{ view: 'browse' }} className="stat-strip" title="Browse every record">
          {stats.map(([n, label]) => <span key={label} className="stat"><span className="stat-n">{n}</span><span className="stat-l">{label}</span></span>)}
        </Link>
      </section>
    </main>
  );
}
