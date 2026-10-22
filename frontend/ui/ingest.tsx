// Ingest: paste raw text, a server-side loop extracts a draft for review.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { EmptyState, I, Notice, PageHeader, type IconName } from './lib';
import { Link, useRouter } from './router';
import { errorMessage, getReviewMode, HttpError, ingest, type ReviewMode } from './api';
import { useAsync } from './use-async';

const SOURCE_TYPES: { k: string; label: string; glyph: IconName }[] = [
  { k: 'brain-dump', label: 'Brain-dump', glyph: 'survey' },
  { k: 'pasted-doc', label: 'Pasted doc', glyph: 'grep' },
  { k: 'transcript', label: 'Transcript', glyph: 'interp' },
  { k: 'code', label: 'Codebase', glyph: 'trace' },
];
// Shown while the request runs. They cycle for liveliness; they are not
// progress, which the server does not report.
const PHASES = ['Reading source', 'Extracting entities & statements', 'Resolving names & links against the knowledge base', 'Assembling draft'];

// What happens to an extracted draft, in the words of the current review mode.
export function draftFate(mode: ReviewMode | null, noun: string): ReactNode {
  if (mode === 'review-and-apply') return <>The {noun} goes <b>straight to the AI reviewer</b>, so you cannot edit it first, and a draft the reviewer accepts is <b>applied without a person approving it</b>.</>;
  if (mode === 'review-only') return <>The {noun} goes <b>straight to the AI reviewer</b>, so you cannot edit it first. The review is advisory: a curator still approves or rejects it.</>;
  if (mode === 'off') return <>You get a <b>draft to review</b> and edit; nothing reaches the knowledge base until a curator approves it.</>;
  return <>It becomes a <b>draft</b> that is reviewed before it reaches the knowledge base.</>;
}

type Phase =
  | { phase: 'compose' }
  | { phase: 'two-drafts'; draftId: string; aliasDraftId: string; submitted: boolean }
  | { phase: 'processing'; startedAt: number }
  | { phase: 'nothing'; reason: string }
  | { phase: 'error'; message: string };

export function IngestSurface() {
  const { go } = useRouter();
  const [state, setState] = useState<Phase>({ phase: 'compose' });
  const [source, setSource] = useState('');
  const [sourceType, setSourceType] = useState('brain-dump');
  const [now, setNow] = useState(Date.now);
  const runId = useRef(0);
  const mode = useAsync(getReviewMode).state;
  const reviewMode = mode.status === 'ready' ? mode.data : null;

  const processing = state.phase === 'processing';
  useEffect(() => {
    if (!processing) return;
    const tick = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(tick);
  }, [processing]);
  // A response arriving after the screen is left is dropped.
  useEffect(() => () => { runId.current++; }, []);

  const start = () => {
    if (!source.trim() || processing) return;
    const mine = ++runId.current;
    setState({ phase: 'processing', startedAt: Date.now() });
    ingest(source).then(res => {
      if (mine !== runId.current) return;
      if (res.outcome === 'draft_created' && res.alias_draft_id && res.alias_draft_id !== res.draft_id) {
        setState({ phase: 'two-drafts', draftId: res.draft_id, aliasDraftId: res.alias_draft_id, submitted: !!res.submitted_for_review });
      } else if (res.outcome === 'draft_created') go({ view: 'draft', id: res.draft_id });
      else setState({ phase: 'nothing', reason: res.reason || 'The librarian found nothing worth drafting from this text.' });
    }, (err: unknown) => {
      if (mine !== runId.current) return;
      setState({ phase: 'error', message: err instanceof HttpError && err.status === 403 ? 'You need drafter or writer access to ingest.' : errorMessage(err, 'Ingest failed.') });
    });
  };
  const back = () => setState({ phase: 'compose' });

  if (state.phase === 'two-drafts') {
    return (
      <main className="page"><div className="ingest-stage">
        <PageHeader eyebrow="Ingest" title="Your text became two drafts" blurb="Statements and links go one way, alias suggestions another, because they are decided differently." />
        <div className="result-cards">
          <Link to={{ view: 'draft', id: state.draftId }} className="result-card write">
            <span className="rc-title">Statements, entities and links</span>
            <span className="rc-body">{state.submitted ? 'Submitted to the AI reviewer.' : 'Open: review and edit it, then submit.'} A curator decides the draft as a whole.</span>
            <span className="rc-id mono">{state.draftId} →</span>
          </Link>
          <Link to={{ view: 'draft', id: state.aliasDraftId }} className="result-card">
            <span className="rc-title">Alias suggestions</span>
            <span className="rc-body">New names for existing entities, already submitted. Each alias is accepted or rejected on its own in <b>Names &amp; aliases</b>.</span>
            <span className="rc-id mono">{state.aliasDraftId} →</span>
          </Link>
        </div>
        <div className="row gap-sm"><Link to={{ view: 'names' }} className="btn">Open Names &amp; aliases</Link><button className="btn ghost" onClick={back}>Ingest more text</button></div>
      </div></main>
    );
  }

  if (state.phase === 'nothing' || state.phase === 'error') {
    return (
      <main className="page"><div className="ingest-stage">
        <div className="ingest-proc">
          <EmptyState title={state.phase === 'nothing' ? 'Nothing to ingest' : 'Ingest failed'} blurb={state.phase === 'nothing' ? state.reason : state.message}>
            <button className="btn" onClick={back}>Back to your text</button>
          </EmptyState>
        </div>
      </div></main>
    );
  }

  if (state.phase === 'processing') {
    const elapsed = (now - state.startedAt) / 1000;
    const active = Math.floor(elapsed / 2.6) % PHASES.length;
    return (
      <main className="page"><div className="ingest-stage">
        <div className="ingest-proc">
          <div className="ip-top">
            <div className="ip-orb"><span className="ring" /><span className="core" /></div>
            <div className="ip-headline"><div className="h">The librarian is reading your {sourceType.replace('-', ' ')}…</div><div className="s">server-side extraction · emits a draft for your review</div></div>
            <div className="ip-clock">{elapsed.toFixed(1)}s</div>
          </div>
          <div className="ip-phases" role="status">
            {PHASES.map((label, i) => (
              <div key={label} className={`ip-phase${i === active ? ' active' : ''}`}>
                <span className="pp-mark" /><span>{label}</span><span className="pp-t">{i === active ? 'working' : 'queued'}</span>
              </div>
            ))}
          </div>
          <div className="ip-leave-note"><I.timeout className="lc" width="16" height="16" /><span>This can take a minute or two. You can leave: the draft will be under <Link to={{ view: 'drafts' }}>Drafts</Link>{reviewMode && reviewMode !== 'off' ? ', already with the AI reviewer' : ''}.</span></div>
        </div>
      </div></main>
    );
  }

  const words = source.trim() ? source.trim().split(/\s+/).length : 0;
  return (
    <main className="page"><div className="ingest-stage">
      <PageHeader eyebrow="Add knowledge" title={<>Drop in raw text. The <em className="write">librarian</em> structures it.</>}
        blurb={<>Paste a brain-dump, a doc or a transcript. A server-side agent decides the entities, statements, kinds, links and mentions. {draftFate(reviewMode, 'draft')} Alias suggestions go to a separate draft.</>} />
      {reviewMode === 'review-and-apply' && <Notice tone="warn">Automatic review applies accepted drafts. Text you extract here can reach the knowledge base without a person reading it. <Link to={{ view: 'settings', section: 'review' }}>Draft review settings</Link></Notice>}
      <div className="src-type-row" role="group" aria-label="Source type">
        <span className="ll">source</span>
        {SOURCE_TYPES.map(st => (
          <button key={st.k} className={`src-chip${sourceType === st.k ? ' on' : ''}`} aria-pressed={sourceType === st.k} onClick={() => setSourceType(st.k)}>
            {I[st.glyph]({ className: 'sc-glyph' })}{st.label}
          </button>
        ))}
      </div>
      <div className="ingest-field">
        <textarea value={source} onChange={e => setSource(e.target.value)} spellCheck={false} aria-label="Text to ingest"
          placeholder="Paste raw text here. The more context, the richer the extracted draft…" />
        <div className="ingest-foot">
          <span className="if-meta"><b>{words}</b> words · <b>{source.length}</b> chars</span>
          <span className="if-spacer" />
          <button className="btn write" disabled={!source.trim()} onClick={start}><I.ask width="15" height="15" />Extract to draft</button>
        </div>
      </div>
      <p className="hint">Extraction runs on the server and can take a while; the draft appears under Drafts when it is done.</p>
    </div></main>
  );
}
