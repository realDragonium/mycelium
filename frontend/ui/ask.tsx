// Ask: the agentic answer. Honest working state, one of two result shapes
// (answered or needs clarification), real errors with retry, and a way to
// report what the knowledge base could not answer.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { I, useAskExternal, useMe } from './lib';
import { Link, useRouter } from './router';
import { ask, errorMessage, isAuthError, isScoped, knowledgeGaps, type AskEvent, type AskTrace, type Confidence, type RawAnswered, type RawClarification } from './api';
import { substrate } from './data';

/* ---- view shapes ---- */
const CONF_VALUE: Record<Confidence, number> = { high: 0.85, medium: 0.6, low: 0.35 };
interface TraceStep { phase: string; detail: string; refs: string[] }
interface Answered {
  outcome: 'answered'; question: string; degraded: boolean;
  interpretation: { text: string; reframed: boolean; reframedNote: string };
  confidence: { level: Confidence; value: number; rationale: string };
  answer: string[]; gaps: string[]; provenance: string[]; trace: TraceStep[];
}
interface Clarification {
  outcome: 'needs_clarification'; question: string; clarifyingQuestion: string;
  interpretations: { label: string; note: string; wouldRetrieve: string[] }[];
  known: string[];
}
type AskView = Answered | Clarification;

function splitParas(answer: string): string[] {
  const text = answer.trim();
  if (!text) return ['The knowledge base returned no prose for this question.'];
  const paras = text.split(/\n{2,}/).map(p => p.trim()).filter(Boolean);
  return paras.length ? paras : [text];
}
function shortLabel(s: string): string {
  const words = s.trim().split(/\s+/);
  return words.length > 7 ? words.slice(0, 7).join(' ') + '…' : words.join(' ') || 'Interpretation';
}
function splitKnown(known: string | string[] | undefined): string[] {
  if (Array.isArray(known)) return known.filter(Boolean);
  const text = (known || '').trim();
  return text ? text.split(/(?<=[.!?])\s+(?=[A-Z0-9])/).map(s => s.trim()).filter(Boolean) : [];
}
function buildTrace(t: AskTrace, provenance: string[]): TraceStep[] {
  const tools = t.tool_calls || [];
  const steps: TraceStep[] = [{
    phase: 'recon',
    detail: `Read "${t.question || ''}" with ${t.model || 'the model'}: ${t.op_count || 0} retrieval op${t.op_count === 1 ? '' : 's'} against the knowledge base.`,
    refs: [],
  }];
  const ledger = t.sub_question_ledger || [];
  if (ledger.length) steps.push({ phase: 'traverse', detail: ledger.map(l => `• ${l.sub_question}${l.status ? ` (${l.status})` : ''}`).join('  '), refs: [] });
  else if (tools.length) {
    const names = [...new Set(tools.map(c => c.name).filter(Boolean))];
    steps.push({ phase: 'traverse', detail: `Called ${tools.length} tool${tools.length === 1 ? '' : 's'}: ${names.join(', ')}.`, refs: [] });
  }
  steps.push({ phase: 'synthesis', detail: `Composed the answer${t.degraded || t.forced_finalize ? ' (degraded: forced finalize)' : ''}.`, refs: provenance });
  return steps;
}

// The server never reports a timeout: an exhausted budget comes back answered
// with low confidence and trace.forced_finalize set, shown as degraded.
function adaptAnswered(raw: RawAnswered, question: string): Answered {
  const trace = raw.trace || {};
  const degraded = !!(trace.forced_finalize || trace.degraded);
  const n = raw.gaps.length;
  const base = n ? `Grounded in the cited statements; ${n} explicit gap${n === 1 ? '' : 's'} lowered confidence.` : 'Grounded directly in the cited statements.';
  return {
    outcome: 'answered', question, degraded,
    interpretation: {
      text: raw.interpretation.resolved_to || raw.interpretation.as_asked || question,
      reframed: !!raw.interpretation.reframed,
      reframedNote: raw.interpretation.reframe_reason || 'reframed against what the knowledge base actually holds',
    },
    confidence: { level: raw.confidence, value: CONF_VALUE[raw.confidence], rationale: degraded ? `${base} The loop was force-finalised under load; treat this answer as provisional.` : base },
    answer: splitParas(raw.answer), gaps: raw.gaps, provenance: raw.provenance,
    trace: buildTrace(trace, raw.provenance),
  };
}
function adaptClarification(raw: RawClarification, question: string): Clarification {
  return {
    outcome: 'needs_clarification', question, clarifyingQuestion: raw.question || 'Which reading did you mean?',
    interpretations: raw.candidates.map(c => ({
      label: shortLabel(c.interpretation || ''), note: c.interpretation || '',
      wouldRetrieve: c.would_pull == null ? [] : ([] as string[]).concat(c.would_pull),
    })),
    known: splitKnown(raw.known_so_far),
  };
}

/* ---- pieces ---- */
function ConfidenceMeter({ confidence }: { confidence: Answered['confidence'] }) {
  const on = confidence.level === 'high' ? 3 : confidence.level === 'medium' ? 2 : 1;
  return (
    <span className={`conf ${confidence.level}`}>
      <span className="c-dots">{[0, 1, 2].map(i => <span key={i} className={`c-dot${i < on ? ' on' : ''}`} />)}</span>
      <span className="c-label">{confidence.level} confidence · {confidence.value.toFixed(2)}</span>
    </span>
  );
}

function Panel({ icon, title, count, cls = '', children, collapsible, openDefault = true }: {
  icon: ReactNode; title: string; count?: ReactNode; cls?: string; children: ReactNode; collapsible?: boolean; openDefault?: boolean;
}) {
  const [open, setOpen] = useState(openDefault);
  const head = <>
    <span className="ph-icon">{icon}</span><span className="ph-title">{title}</span>
    {count != null && <span className="ph-count">{count}{collapsible ? (open ? ' · hide' : ' · show') : ''}</span>}
  </>;
  return (
    <section className={`panel ${cls}`}>
      {collapsible
        ? <button className="panel-head" aria-expanded={open} onClick={() => setOpen(o => !o)}>{head}</button>
        : <header className="panel-head">{head}</header>}
      {open && <div className="panel-body">{children}</div>}
    </section>
  );
}

// Files a knowledge gap through report_knowledge_gap; the text is editable
// before it is sent.
function ReportGap({ question, detail }: { question: string; detail: string }) {
  const scoped = isScoped(useMe());
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(`Ask could not answer: "${question}". ${detail}`);
  const [state, setState] = useState<{ phase: 'idle' | 'sending' | 'sent' } | { phase: 'error'; message: string }>({ phase: 'idle' });
  if (scoped) return null;
  if (state.phase === 'sent') return <p className="flag answered report-done"><I.check width="13" height="13" />Gap reported. It is listed under <Link to={{ view: 'gaps' }}>Knowledge gaps</Link>.</p>;
  if (!open) return <button className="btn" onClick={() => setOpen(true)}><I.gap width="14" height="14" />Report a gap</button>;
  const send = () => {
    setState({ phase: 'sending' });
    knowledgeGaps.report(text.trim()).then(
      () => setState({ phase: 'sent' }),
      (err: unknown) => setState({ phase: 'error', message: errorMessage(err, 'The report could not be filed.') }),
    );
  };
  return (
    <div className="report-gap">
      <label className="field"><span>Gap report</span><textarea value={text} onChange={e => setText(e.target.value)} rows={3} /></label>
      <div className="row gap-sm">
        <button className="btn primary" disabled={!text.trim() || state.phase === 'sending'} onClick={send}>{state.phase === 'sending' ? 'Reporting…' : 'File gap report'}</button>
        <button className="btn ghost" onClick={() => setOpen(false)}>Cancel</button>
      </div>
      {state.phase === 'error' && <p className="form-error" role="alert">{state.message}</p>}
    </div>
  );
}

function StatementRef({ id, index, role }: { id: string; index: number; role: string }) {
  const s = substrate.index.statements[id];
  if (!s) return null;
  return (
    <Link to={{ view: 'statement', id }} className="prov-item">
      <span className="pv-num">[{index}]</span>
      <span className="pv-body"><span className="pv-title">{s.title || s.text}</span><span className="pv-role"><span>{id}</span> · {role}</span></span>
      <I.arrow className="pv-arrow" width="15" height="15" />
    </Link>
  );
}

function AnsweredView({ r }: { r: Answered }) {
  return (
    <div className="answer-card reveal">
      <div className="answer-top">
        <div className="answer-flags">
          <span className="flag answered"><I.check width="13" height="13" />answered</span>
          {r.degraded && <span className="flag reframed"><I.warn width="13" height="13" />degraded · forced finalize</span>}
          {r.interpretation.reframed && <span className="flag reframed"><I.warn width="13" height="13" />reframed · false premise</span>}
          <ConfidenceMeter confidence={r.confidence} />
        </div>
      </div>
      <div className="answer-prose">{r.answer.map((p, i) => <p key={i}>{p}</p>)}</div>
      <div className="conf-rationale"><b>Confidence: {r.confidence.level}.</b> {r.confidence.rationale}</div>
      <div className="ask-panels">
        <Panel icon={<I.interp width="16" height="16" />} title="Interpretation" cls="reveal-2">
          <div className="interp-text">
            {r.interpretation.text}
            {r.interpretation.reframed && <span className="reframe-note">⟂ {r.interpretation.reframedNote}</span>}
          </div>
        </Panel>
        <Panel icon={<I.gap width="16" height="16" />} title="Gaps" count={r.gaps.length} cls="gaps reveal-2">
          {r.gaps.map((g, i) => <div key={i} className="gap-item"><span className="gi-mark">—</span><span>{g}</span></div>)}
          {r.gaps.length === 0 && <p className="muted small">The answer reports no gaps.</p>}
          {r.gaps.length > 0 && <ReportGap question={r.question} detail={`Gaps: ${r.gaps.join('; ')}`} />}
        </Panel>
        <Panel icon={<I.prov width="16" height="16" />} title="Provenance" count={`${r.provenance.length} statement${r.provenance.length === 1 ? '' : 's'}`} cls="reveal-3">
          {r.provenance.map((id, i) => <StatementRef key={id} id={id} index={i + 1} role={substrate.index.statements[id]?.kind || 'statement'} />)}
        </Panel>
        <Panel icon={<I.trace width="16" height="16" />} title="Retrieval trace" count={`${r.trace.length} steps`} cls="trace reveal-3" collapsible openDefault={false}>
          {r.trace.map((st, i) => (
            <div key={i} className="trace-step">
              <span className="ts-phase">{st.phase}</span>
              <div>
                <div className="ts-detail">{st.detail}</div>
                {st.refs.length > 0 && <div className="ts-refs">{st.refs.map(id => <Link key={id} to={{ view: 'statement', id }} className="ref-pill">{id}</Link>)}</div>}
              </div>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function ClarificationView({ r, onPick }: { r: Clarification; onPick: (io: Clarification['interpretations'][number]) => void }) {
  return (
    <div className="clarify-card reveal">
      <div className="clarify-top">
        <div className="clarify-flag"><I.interp width="14" height="14" />needs clarification · no answer committed</div>
        <div className="clarify-q">{r.clarifyingQuestion}</div>
      </div>
      <div className="clarify-body">
        <div className="section-label">Candidate interpretations: pick one to answer</div>
        <div className="interp-options">
          {r.interpretations.map((io, i) => (
            <button key={i} className="interp-opt" onClick={() => onPick(io)}>
              <span className="io-head"><span className="io-name">{io.label}</span><span className="io-pick">answer this →</span></span>
              <span className="io-note">{io.note}</span>
              <span className="io-retrieve">
                <span className="io-rlabel">would retrieve</span>
                {io.wouldRetrieve.map(id => <span key={id} className="lt" title={substrate.index.statements[id]?.title || id}>{id}</span>)}
              </span>
            </button>
          ))}
        </div>
        <div className="section-label">What is known so far</div>
        <div className="known-list">
          {r.known.map((k, i) => <div key={i} className="known-item"><I.check className="ki-check" width="15" height="15" /><span>{k}</span></div>)}
        </div>
      </div>
    </div>
  );
}

type Phase =
  | { phase: 'working'; startedAt: number }
  | { phase: 'done'; result: AskView }
  | { phase: 'error'; detail: string; cancelled: boolean };

export function AskSurface({ query }: { query: string }) {
  const external = useAskExternal();
  const { go } = useRouter();
  const [asked, setAsked] = useState(query);
  const [state, setState] = useState<Phase>(() => ({ phase: 'working', startedAt: Date.now() }));
  const [attempt, setAttempt] = useState(0);
  const [progress, setProgress] = useState('');
  const [partial, setPartial] = useState('');
  const [now, setNow] = useState(Date.now);
  const active = useRef<AbortController | null>(null);

  useEffect(() => {
    if (external === true) go({ view: 'find', query, mode: 'semantic' }, { replace: true });
  }, [external, go, query]);

  // A new run starts whenever the question or attempt changes; its state is
  // reset by the handlers that trigger it, so the effect only subscribes.
  useEffect(() => {
    if (external !== false) return;
    const controller = new AbortController();
    active.current = controller;
    const onEvent = (event: AskEvent) => {
      if (event.type === 'progress') setProgress(event.message);
      if (event.type === 'answer_delta') setPartial(text => text + event.text);
      if (event.type === 'answer_reset') setPartial('');
    };
    const tick = setInterval(() => setNow(Date.now()), 100);
    ask(asked, controller.signal, onEvent).then(raw => {
      clearInterval(tick);
      if (controller.signal.aborted) return;
      setPartial('');
      setState({ phase: 'done', result: raw.outcome === 'answered' ? adaptAnswered(raw, asked) : adaptClarification(raw, asked) });
    }, (err: unknown) => {
      clearInterval(tick);
      const cancelled = err instanceof DOMException && err.name === 'AbortError';
      if (controller.signal.aborted && !cancelled) return;
      setState({
        phase: 'error', cancelled,
        detail: cancelled ? 'The request was cancelled. Any text shown is incomplete.'
          : isAuthError(err) ? 'You need an authenticated session to ask.'
          : errorMessage(err, 'The knowledge base did not respond.'),
      });
    });
    return () => { clearInterval(tick); controller.abort(); };
  }, [asked, attempt, external]);

  const restart = (question: string) => {
    setProgress(''); setPartial(''); setState({ phase: 'working', startedAt: Date.now() });
    if (question === asked) setAttempt(a => a + 1); else setAsked(question);
  };
  const working = state.phase === 'working';
  if (external !== false) return null;

  return (
    <main className="page">
      <div className="ask-stage">
        <div className="ask-q">
          <div className="aq-label"><span className="dot" />question</div>
          <h1 className="aq-text">{asked}</h1>
        </div>

        {working && (
          <div className="ask-working">
            <div className="aw-row">
              <div className="aw-orb"><span className="ring" /><span className="core" /></div>
              <div className="aw-text">
                <div className="aw-title">Checking the knowledge base…</div>
                <div className="aw-sub" role="status" aria-live="polite">{progress || 'Waiting for retrieval to start…'}</div>
              </div>
              <div className="aw-clock">{((now - state.startedAt) / 1000).toFixed(1)}s</div>
            </div>
            <button className="btn" onClick={() => active.current?.abort()}>Cancel</button>
            <div className="aw-bar" />
            <div className="aw-note">Progress reports completed checks. Answer text stays provisional until the result is complete.</div>
          </div>
        )}
        {partial && state.phase !== 'done' && (
          <section className="answer-card">
            <div className="answer-top muted small">{working ? 'Composing answer · provisional' : 'Incomplete answer'}</div>
            <div className="answer-prose pre-wrap">{partial}</div>
          </section>
        )}
        {state.phase === 'error' && (
          <div className="ask-error reveal">
            <I.timeout className="ae-icon" width="34" height="34" />
            <div className="ae-title">{state.cancelled ? 'Ask cancelled' : 'Ask did not complete'}</div>
            <div className="ae-detail">{state.detail}</div>
            <div className="ae-actions">
              <button className="btn primary" onClick={() => restart(asked)}>Retry</button>
            </div>
            {!state.cancelled && <ReportGap question={asked} detail={state.detail} />}
          </div>
        )}
        {state.phase === 'done' && state.result.outcome === 'answered' && <AnsweredView r={state.result} />}
        {state.phase === 'done' && state.result.outcome === 'needs_clarification' && (
          <ClarificationView r={state.result} onPick={io => restart(`${query}: interpreted as ${io.label}. ${io.note}`)} />
        )}
      </div>
    </main>
  );
}
