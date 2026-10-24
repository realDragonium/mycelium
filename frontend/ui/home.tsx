// Home: the Ask | Find entry point, what the knowledge base holds, and what
// is waiting for a person.
import { useCallback } from 'react';
import { CommandBar } from './command-bar';
import { I, useAskExternal, useGoIngest, useMe } from './lib';
import { Link } from './router';
import { getJSON, getSubstrateCounts, isScoped, type KnowledgeGap } from './api';
import { asksPerson, type DraftSummary } from './draft-review';
import { HomeSetup } from './setup';
import { useAsync } from './use-async';

const loadQueue = (scoped: boolean) => scoped ? Promise.resolve(null) : Promise.all([
  getJSON<{ drafts: DraftSummary[] }>('/api/drafts?status=submitted'),
  getJSON<{ drafts: DraftSummary[] }>('/api/drafts?status=open'),
  getJSON<{ gaps: KnowledgeGap[] }>('/api/knowledge-gaps?status=open'),
]);

export function HomeScreen() {
  const scoped = isScoped(useMe());
  const askExternal = useAskExternal();
  const goIngest = useGoIngest();
  const queue = useAsync(useCallback(() => loadQueue(scoped), [scoped])).state;
  const counts = useAsync(getSubstrateCounts).state;
  const [submittedDrafts, openDrafts, openGaps] = queue.status === 'ready' && queue.data ? queue.data : [{ drafts: [] }, { drafts: [] }, { gaps: [] }];
  const submitted = submittedDrafts.drafts.length;
  const open = openDrafts.drafts.length;
  const questions = submittedDrafts.drafts.filter(d => asksPerson(d.review_assessment)).length;
  const gaps = openGaps.gaps.length;

  const n = counts.status === 'ready' ? counts.data : { statements: 0, entities: 0, names: 0, links: 0, entity_links: 0 };
  const stats: [number, string][] = [
    [n.statements, 'statements'], [n.entities, 'entities'], [n.names, 'names'],
    [n.links, 'links'], [n.entity_links, 'entity links'],
  ];

  return (
    <main className="page home">
      <div className="home-hero">
        <div className="eyebrow">Mycelium · knowledge base</div>
        <h1 className="home-title">Interrogate a substrate<br />built to be <em>read by machines</em>.</h1>
        <p className="home-blurb">
          Knowledge enters through <b>ingest</b> or connected agents, and waits as a draft until someone approves it.
          {askExternal === true
            ? <> <b>Find</b> returns raw, scored matches for you to judge.</>
            : <> Read it back two ways: <b>Ask</b> for a reasoned answer with its gaps and provenance, or <b>Find</b> for raw, scored matches you judge.</>}
        </p>
      </div>

      <div className="home-cmd"><CommandBar hero /></div>

      <HomeSetup />

      <div className={`tier-cards${askExternal === true ? ' find-only' : ''}`}>
        {askExternal !== true && <div className="tier-card ask">
          <div className="tc-head"><span className="tc-dot" /><span className="tc-name">Ask</span><span className="tc-kind">agentic · slow</span></div>
          <p>A reasoning loop returns one answer with confidence, the interpretation it used, explicit gaps, provenance and a trace.</p>
        </div>}
        <div className="tier-card find">
          <div className="tc-head"><span className="tc-dot" /><span className="tc-name">Find</span><span className="tc-kind">deterministic · fast</span></div>
          <p>Semantic, grep and survey return raw statements with relevance scores. Nothing is hidden; the long tail is shown, faded.</p>
        </div>
      </div>

      {!scoped && <section className="home-section" aria-labelledby="home-attention">
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
      </section>}

      <section className="home-section" aria-labelledby="home-holds">
        <h2 id="home-holds" className="section-label">What it holds</h2>
        <Link to={{ view: 'browse' }} className="stat-strip" title="Browse every record">
          {stats.map(([n, label]) => <span key={label} className="stat"><span className="stat-n">{n}</span><span className="stat-l">{label}</span></span>)}
        </Link>
      </section>
    </main>
  );
}
