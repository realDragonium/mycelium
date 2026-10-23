// Drafts: every change waits here as a draft before it reaches the knowledge
// base. Authors submit; curators (real writers or admins) approve, which
// replays the operations, or reject, which drops them.
import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { draftReviewProviderName } from './ai-settings';
import { GraphView } from './graph';
import { EmptyState, I, KindTag, LinkTag, LoadError, Loading, Notice, PageHeader, formatDate, relTime, useGoIngest } from './lib';
import { Link, useRouter, type Route } from './router';
import { HttpError, deleteJSON, enc, errorMessage, getJSON, patchJSON, postJSON } from './api';
import { buildIndex, substrate, type Entity, type EntityLink, type Link as SubstrateLink, type Name, type Statement, type SubstrateData } from './data';
import { dataOf, useAsync } from './use-async';

/* ============================ wire shapes ============================ */
type DraftStatus = 'open' | 'submitted' | 'approved' | 'rejected' | 'withdrawn';
interface Correction { action: string; operation_ref?: string | null; tool_name?: string | null; reason: string; payload_json?: string | null }
interface Contradiction { statement_id: string; resolution: string }
interface Answer { run_id: string; questions: string[]; answer: string; answered_by: string; answered_at: string }
interface Assessment {
  run_id: string; status: 'running' | 'completed' | 'failed'; label?: string | null; stale?: boolean;
  provider?: string | null; model?: string | null; reasoning_effort?: string | null; mode?: string | null;
  application?: 'unapplied' | 'applied' | 'rejected' | 'needs_human' | null; draft_revision?: number;
  rationale?: string | null; detail?: string | null; questions: string[]; corrections: Correction[];
  contradictions?: Contradiction[]; answers?: Answer[]; attempt?: number; previous_failure?: string | null;
}
// The reviewer stopped to ask a person rather than reject: the draft waits
// until a curator answers, then the reviewer runs again with the answer.
export const asksPerson = (a: Assessment | null | undefined) => !!a && a.status === 'completed' && a.application === 'needs_human';
export interface DraftSummary {
  id: string; title: string | null; status: DraftStatus; created_at: string; created_by: string | null;
  submitted_at: string | null; decided_at: string | null; op_count?: number; review_assessment: Assessment | null;
}
type Payload = Record<string, unknown>;
interface DraftOp { seq: number; kind: string; payload: Payload; provenance: { source?: string } | null }
interface Draft extends DraftSummary { ops: DraftOp[] }
// Statements the server refused while applying a draft by hand; nothing was applied.
interface RejectedStatement { seq: number; kind: string; text: string | null; reasons: string[] }
const rejectionsOf = (e: unknown): RejectedStatement[] => {
  if (!(e instanceof HttpError) || e.status !== 422) return [];
  const { detail } = e;
  return detail && typeof detail === 'object' && 'rejections' in detail && Array.isArray(detail.rejections) ? detail.rejections as RejectedStatement[] : [];
};
interface ReviewSettings { mode: string; can_review: boolean; provider?: string | null; model?: string | null }

const drafts = {
  list: () => getJSON<{ drafts: DraftSummary[] }>('/api/drafts?status=all').then(r => r.drafts),
  get: (id: string) => getJSON<{ draft: Draft }>(`/api/drafts/${enc(id)}`).then(r => r.draft),
  act: (id: string, action: 'submit' | 'withdraw' | 'approve' | 'reject' | 'review') => postJSON<unknown>(`/api/drafts/${enc(id)}/${action}`),
  answer: (id: string, runId: string, answer: string) => postJSON<unknown>(`/api/drafts/${enc(id)}/review/answer`, { run_id: runId, answer }),
  discardOp: (id: string, seq: number) => deleteJSON<unknown>(`/api/drafts/${enc(id)}/ops/${seq}`),
  editOp: (id: string, seq: number, payload: Payload) => patchJSON<unknown>(`/api/drafts/${enc(id)}/ops/${seq}`, { payload }),
  reviewSettings: () => getJSON<ReviewSettings>('/api/draft-review/settings'),
};

const isActive = (d: DraftSummary) => d.status === 'open' || d.status === 'submitted';
const str = (v: unknown): string => typeof v === 'string' ? v : v == null ? '' : JSON.stringify(v);
const arr = (v: unknown): Payload[] => Array.isArray(v) ? v.filter((x): x is Payload => !!x && typeof x === 'object') : [];

/* ============================ AI review ============================ */
const LABELS: Record<string, string> = { good: 'Good', changes_suggested: 'Changes suggested', reject: 'Reject suggested', needs_context: 'Needs context' };

function assessmentResult(a: Assessment): string {
  if (asksPerson(a)) return 'Question for a curator';
  if (a.status === 'running') return 'Running';
  if (a.status === 'failed') return 'Failed';
  return (a.label && LABELS[a.label]) || 'Completed';
}

function AssessmentBadge({ assessment }: { assessment: Assessment }) {
  return <span className={`review-badge${asksPerson(assessment) ? ' asks' : ''}`}>AI review: {assessmentResult(assessment)}{assessment.stale ? ' · stale' : ''}</span>;
}

function AssessmentPanel({ assessment }: { assessment: Assessment }) {
  return (
    <section className="card review-card" aria-label="AI review">
      <div className="row between"><AssessmentBadge assessment={assessment} /><span className="muted small">{draftReviewProviderName(assessment.provider)} · {assessment.model || 'model not recorded'} · effort {assessment.reasoning_effort ?? 'model default'}</span></div>
      <p className="small">
        {assessment.mode === 'review-only' ? 'Review only: this review does not edit, reject or apply the draft.' : 'Review and apply.'}
        {' '}Status: {assessment.status}.{' '}
        {assessment.application === 'applied' ? 'The review applied this draft.'
          : assessment.application === 'rejected' ? 'The review rejected this draft.'
          : assessment.application === 'needs_human' ? 'The reviewer is waiting for a curator to answer its questions.'
          : 'Nothing was applied or rejected automatically.'}
      </p>
      {assessment.stale && <Notice tone="warn">This assessment is stale: it reviewed revision {assessment.draft_revision}, and the draft has changed since.</Notice>}
      {assessment.rationale && <p className="pre-wrap">{assessment.rationale}</p>}
      {assessment.detail && <p className="pre-wrap">{assessment.detail}</p>}
      {assessment.questions.length > 0 && !asksPerson(assessment) && <><h3 className="section-label">Questions</h3><ul>{assessment.questions.map((q, i) => <li key={i}>{q}</li>)}</ul></>}
      {!!assessment.contradictions?.length && <>
        <h3 className="section-label">Contradictions with existing knowledge</h3>
        <ul>{assessment.contradictions.map((c, i) => <li key={i}><Ref id={c.statement_id} />: {c.resolution}</li>)}</ul>
      </>}
      {!!assessment.previous_failure && <p className="hint">Attempt {assessment.attempt}; the previous attempt failed: {assessment.previous_failure}</p>}
      {assessment.corrections.length > 0 && <>
        <h3 className="section-label">Suggested corrections</h3>
        <ul>{assessment.corrections.map((c, i) => (
          <li key={i}>
            <b>{c.action}</b>{c.operation_ref ? ` ${c.operation_ref}` : ''}{c.tool_name ? ` · ${c.tool_name}` : ''}: {c.reason}
            {c.payload_json && <details><summary>Proposed payload</summary><pre className="code">{c.payload_json}</pre></details>}
          </li>
        ))}</ul>
      </>}
    </section>
  );
}

/* ============================ operations ============================ */
type Category = 'statements' | 'entities' | 'names' | 'links' | 'flagged';
function categoryOf(op: DraftOp): Category {
  const k = op.kind;
  if (k === 'flag') return 'flagged';
  if (['upsert_statement', 'upsert_statements', 'patch_statement', 'replace_text', 'merge_statements', 'delete_statement'].includes(k)) return 'statements';
  if (['upsert_entity', 'delete_entity', 'merge_entities'].includes(k)) return 'entities';
  if (['upsert_name', 'alias_suggestion', 'rename_name', 'move_name', 'delete_name'].includes(k)) return 'names';
  return 'links';
}

// A `flag` records a fragment the retired ingest_text pipeline would not decide
// on its own. Nothing writes flags any more, but older drafts carry them; they
// never replay. The stage names who raised it; the sentence is what a curator
// can act on.
const FLAG_REASONS: Record<string, [string, string]> = {
  unsplit: ['segmenter', 'A compound the segmenter could not cut into separate statements.'],
  rejected: ['phrasing catalog', 'The wording was refused before the fragment was classified.'],
  ambiguous: ['shape matching', 'More than one shape matched, so the statement kind stayed undecided.'],
  unmatched: ['shape matching', 'No shape matched, so no statement kind could be assigned.'],
  phrasing: ['planner', 'Classified, then refused by the phrasing catalog.'],
  flip: ['planner', 'A link on this statement runs against a directional rule.'],
  depends_on_rejected: ['planner', 'It builds on another fragment that was itself rejected.'],
  cue: ['cue gate', 'The connective joining two fragments could not be typed, so both were written without a link between them.'],
};

function FlagExplanation({ op }: { op: DraftOp }) {
  const reason = str(op.payload.reason);
  const known = Object.prototype.hasOwnProperty.call(FLAG_REASONS, reason) ? FLAG_REASONS[reason] : null;
  return (
    <div className="op-flag-reason">
      <I.warn className="ofr-i" width="15" height="15" />
      <div>
        <div className="mono small">{known ? known[0] : op.provenance?.source || 'pipeline'} · {reason || 'unknown'}</div>
        <div>{known ? known[1] : 'This stage refused the fragment; see the detail below.'}</div>
        {!!op.payload.detail && <div className="mono small pre-wrap">{str(op.payload.detail)}</div>}
        <div className="muted small">A flag is a record, not a queued write: approving the draft replays none of them.</div>
      </div>
    </div>
  );
}

function routeFor(id: string): Route | null {
  if (substrate.index.entities[id]) return { view: 'entity', id };
  if (substrate.index.statements[id]) return { view: 'statement', id };
  return null;
}

function Ref({ id }: { id: unknown }) {
  const key = str(id);
  const idx = substrate.index;
  const label = idx.statements[key]?.title || idx.entities[key]?.name || key;
  const to = routeFor(key);
  return to ? <Link to={to} className="lp" title={label}>{label}</Link> : <span className="lp" title={label}>{label}</span>;
}

function KV({ obj }: { obj: Payload }) {
  const entries = Object.entries(obj);
  if (!entries.length) return null;
  return <div className="op-kv">{entries.map(([k, v]) => <span key={k}><span className="k">{k}</span> {str(v)}</span>)}</div>;
}

function OpBody({ op }: { op: DraftOp }) {
  const p = op.payload;
  switch (op.kind) {
    case 'alias_suggestion': {
      const proposal = (p.proposal || {}) as Payload;
      const evidence = (p.evidence || {}) as Payload;
      return <div>
        <div className="op-name-line"><span className="alias-q">“{str(proposal.alias)}”</span><span className="arr">→</span><Ref id={proposal.entity_id} /></div>
        <p className="small">{p.status === 'pending' ? 'Needs a decision' : str(p.status)} in <Link to={{ view: 'names' }}>Names &amp; aliases</Link>.</p>
        {!!evidence.quote && <blockquote>{str(evidence.quote)}</blockquote>}
        {!!proposal.reason && <p className="small muted">{str(proposal.reason)}</p>}
      </div>;
    }
    case 'upsert_statement':
      return <><div className="op-kind"><KindTag kind={str(p.kind)} /></div><div className="op-stmt-text">{str(p.text)}</div></>;
    case 'upsert_statements': {
      const stmts = arr(p.statements);
      return <>
        <div className="mono small muted">{stmts.length} statement{stmts.length === 1 ? '' : 's'}</div>
        {stmts.map((s, i) => <div key={i} className="op-stmt-text row gap-sm">{!!s.kind && <KindTag kind={str(s.kind)} />}<span>{str(s.text)}</span></div>)}
      </>;
    }
    case 'upsert_entity':
      return <><div className="op-ent-name">{str(p.name)}</div><div className="op-ent-desc">{str(p.description)}</div></>;
    case 'upsert_name':
      return <div className="op-name-line"><span className="alias-q">“{str(p.text)}”</span><span className="arr">→</span><Ref id={p.entity_id} /></div>;
    case 'add_links':
      return <>{arr(p.links).map((l, i) => (
        <div key={i} className="op-link-line"><Ref id={l.from_id} /><LinkTag type={str(l.link_type)} hasWhen={!!l.when} /><Ref id={l.to_id} /></div>
      ))}</>;
    case 'add_entity_links':
      return <>{arr(p.links).map((l, i) => (
        <div key={i} className="op-link-line"><Ref id={l.from_entity_id ?? l.from_id} /><LinkTag type={str(l.link_type)} /><Ref id={l.to_entity_id ?? l.to_id} /></div>
      ))}</>;
    case 'merge_statements':
      return <div className="op-link-line"><Ref id={p.from_id} /><span className="arr">⤳ merge into</span><Ref id={p.into_id} /></div>;
    case 'patch_statement': {
      const { id, ...rest } = p;
      return <><div className="op-name-line"><span className="arr">patch</span><Ref id={id} /></div><KV obj={rest} /></>;
    }
    case 'flag':
      return <><div className="op-stmt-text">{str(p.text) || <i className="muted">(no text on this flag)</i>}</div><FlagExplanation op={op} /></>;
    default:
      return <KV obj={p} />;
  }
}

function OpCard({ op, editable, busy, onDiscard, onSave }: {
  op: DraftOp; editable: boolean; busy: boolean; onDiscard: (seq: number) => void; onSave: (seq: number, payload: Payload) => Promise<boolean>;
}) {
  const [json, setJson] = useState<string | null>(null);
  const [parseErr, setParseErr] = useState<string | null>(null);
  const flagged = op.kind === 'flag';
  const save = async () => {
    let parsed: unknown;
    try { parsed = JSON.parse(json || ''); } catch (e) { setParseErr(errorMessage(e)); return; }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) { setParseErr('The payload must be a JSON object.'); return; }
    if (await onSave(op.seq, parsed as Payload)) setJson(null);
  };
  return (
    <div className={`op${flagged ? ' flagged' : ''}`}>
      <div className="op-head">
        <span className="op-plus">{flagged ? '!' : '+'}</span>
        <span className="op-type">{op.kind}</span>
        <span className="op-seq">op {String(op.seq).padStart(2, '0')}</span>
        <span className="op-spacer" />
        {editable && json == null && <>
          <button className="btn ghost xs" disabled={busy} onClick={() => { setParseErr(null); setJson(JSON.stringify(op.payload, null, 2)); }} title="Edit this operation's payload as JSON">Edit</button>
          <button className="op-discard" disabled={busy} title="Discard this operation" aria-label={`Discard operation ${op.seq}`} onClick={() => onDiscard(op.seq)}>✕</button>
        </>}
      </div>
      <div className="op-body">
        {json == null ? <OpBody op={op} /> : (
          <div className="stack-sm">
            <textarea className="code-input" value={json} spellCheck={false} rows={10} aria-label={`Payload of operation ${op.seq}`}
              onChange={e => { setJson(e.target.value); setParseErr(null); }} />
            {parseErr && <p className="form-error" role="alert">{parseErr}</p>}
            <div className="row gap-sm">
              <button className="btn primary sm" disabled={busy} onClick={save}>Save payload</button>
              <button className="btn ghost sm" disabled={busy} onClick={() => setJson(null)}>Cancel</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ============================ scoped graph ============================ */
// The records a draft touches, new ones as placeholder nodes, plus one hop of
// existing context, in the same shape as /api/data so the statement graph can
// draw it unchanged. New and existing records share one style for now.
function scopedSubstrate(ops: DraftOp[], full: SubstrateData): SubstrateData {
  const ents = new Map(full.entities.map(e => [e.id, e]));
  const stmts = new Map(full.statements.map(s => [s.id, s]));
  const nameByText = new Map(full.names.map(n => [n.text, n]));
  const touchedEnt = new Set<string>(), touchedStm = new Set<string>();
  const synthEnts: Entity[] = [], synthStmts: Statement[] = [], synthNames: Name[] = [];
  const synthLinks: SubstrateLink[] = [], synthEntLinks: EntityLink[] = [];
  let n = 0;
  const newId = (kind: string) => `_draft_${kind}_${n++}`;
  const touch = (id: string) => (id.startsWith('ent_') ? touchedEnt : touchedStm).add(id);

  for (const op of ops) {
    const p = op.payload;
    if (op.kind === 'upsert_entity') {
      const existing = nameByText.get(str(p.name));
      if (existing) touchedEnt.add(existing.entity);
      else {
        const id = newId('ent');
        synthEnts.push({ id, name: str(p.name), description: str(p.description) });
        synthNames.push({ id: newId('nam'), text: str(p.name), entity: id });
      }
    } else if (op.kind === 'upsert_statement') {
      const id = newId('stm');
      const mentions = (Array.isArray(p.mentions) ? p.mentions : []).map(str);
      mentions.forEach(m => touchedEnt.add(m));
      synthStmts.push({ id, kind: str(p.kind) || 'claim', text: str(p.text), mentions, title: str(p.text) });
      for (const l of arr(p.links)) { touchedStm.add(str(l.to_id)); synthLinks.push({ from: id, to: str(l.to_id), link_type: str(l.link_type) }); }
    } else if (op.kind === 'delete_entity' || op.kind === 'delete_statement') {
      touch(str(p.id));
    } else if (op.kind === 'merge_entities') {
      if (p.source_id) touchedEnt.add(str(p.source_id));
      if (p.target_id) touchedEnt.add(str(p.target_id));
    } else if (op.kind === 'add_links' || op.kind === 'remove_links') {
      for (const l of arr(p.links)) { touch(str(l.from_id)); touch(str(l.to_id)); synthLinks.push({ from: str(l.from_id), to: str(l.to_id), link_type: str(l.link_type) }); }
    } else if (op.kind === 'add_entity_links' || op.kind === 'remove_entity_links') {
      for (const l of arr(p.links)) {
        const from = str(l.from_entity_id ?? l.from_id), to = str(l.to_entity_id ?? l.to_id);
        touchedEnt.add(from); touchedEnt.add(to);
        synthEntLinks.push({ from, to, link_type: str(l.link_type) });
      }
    }
  }

  const scopedEnt = new Set(touchedEnt), scopedStm = new Set(touchedStm);
  for (const l of full.entity_links || []) {
    if (touchedEnt.has(l.from)) scopedEnt.add(l.to);
    if (touchedEnt.has(l.to)) scopedEnt.add(l.from);
  }
  for (const l of full.links) {
    if (touchedStm.has(l.from)) scopedStm.add(l.to);
    if (touchedStm.has(l.to)) scopedStm.add(l.from);
  }
  for (const s of full.statements) {
    if (touchedStm.has(s.id)) s.mentions.forEach(e => scopedEnt.add(e));
    if (s.mentions.some(e => touchedEnt.has(e))) scopedStm.add(s.id);
  }
  const synthStmIds = new Set(synthStmts.map(s => s.id));
  const inScope = (id: string) => scopedStm.has(id) || synthStmIds.has(id);
  return {
    entities: [...[...scopedEnt].flatMap(id => ents.get(id) || []), ...synthEnts],
    statements: [
      ...[...scopedStm].flatMap(id => { const s = stmts.get(id); return s ? [{ ...s, mentions: s.mentions.filter(e => scopedEnt.has(e)) }] : []; }),
      ...synthStmts,
    ],
    names: [...full.names.filter(nm => scopedEnt.has(nm.entity)), ...synthNames],
    links: [...full.links.filter(l => scopedStm.has(l.from) && scopedStm.has(l.to)), ...synthLinks.filter(l => inScope(l.from) && inScope(l.to))],
    entity_links: [...(full.entity_links || []).filter(l => scopedEnt.has(l.from) && scopedEnt.has(l.to)), ...synthEntLinks],
  };
}

function DraftGraph({ ops }: { ops: DraftOp[] }) {
  const scoped = useMemo(() => scopedSubstrate(ops, substrate.data), [ops]);
  const index = useMemo(() => buildIndex(scoped), [scoped]);
  if (scoped.entities.length + scoped.statements.length === 0) return <p className="muted small">Nothing to draw yet.</p>;
  return <div className="draft-graph"><GraphView data={scoped} index={index} embedded /></div>;
}

/* ============================ the reviewer's question ============================ */
function ReviewerQuestion({ draftId, assessment, onAnswered, onMoved }: {
  draftId: string; assessment: Assessment; onAnswered: () => void; onMoved: (message: string) => void;
}) {
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (!answer.trim() || busy) return;
    setBusy(true); setError(null);
    try { await drafts.answer(draftId, assessment.run_id, answer.trim()); setAnswer(''); onAnswered(); }
    catch (ex) {
      // 400: the reviewer asked again or the draft moved on; show what is current.
      if (ex instanceof HttpError && ex.status === 400) onMoved(`Your answer was not sent (${ex.message.replace(/\.$/, '')}). The reviewer asked again or the draft moved on; it has been reloaded to show where it stands.`);
      else setError(errorMessage(ex, 'The answer could not be sent.'));
    } finally { setBusy(false); }
  };
  return (
    <section className="question-card" aria-labelledby="reviewer-question">
      <div className="qc-head">
        <span className="qc-icon"><I.interp width="18" height="18" /></span>
        <div>
          <h2 id="reviewer-question">The reviewer needs your answer</h2>
          <p className="muted small">Instead of rejecting this draft, the {draftReviewProviderName(assessment.provider)} reviewer stopped to ask a curator. Nothing is applied or rejected until you answer; then it reviews the draft again with your answer.</p>
        </div>
      </div>
      <ol className="qc-questions">{assessment.questions.map((q, i) => <li key={i}>{q}</li>)}</ol>
      {assessment.rationale && <details className="disclosure"><summary>Why it is asking</summary><p className="pre-wrap">{assessment.rationale}</p></details>}
      {assessment.stale && <Notice tone="warn">The draft changed after the reviewer asked. You can still answer; if the reviewer has moved on, the draft reloads.</Notice>}
      <form onSubmit={send} className="stack-sm">
        <label className="field"><span>Your answer</span>
          <textarea className="input" rows={5} maxLength={6000} value={answer} onChange={e => setAnswer(e.target.value)} required
            placeholder="Answer each question. The reviewer reads this as context from a curator, not as evidence for the draft's claims." />
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="row gap-sm">
          <button type="submit" className="btn primary" disabled={busy || !answer.trim()}>{busy ? 'Sending…' : 'Answer and review again'}</button>
          <span className="hint">{answer.length}/6000</span>
        </div>
      </form>
    </section>
  );
}

function PastAnswers({ answers }: { answers: Answer[] }) {
  if (!answers.length) return null;
  return (
    <details className="card disclosure">
      <summary>Earlier questions and answers · {answers.length}</summary>
      {answers.map((a, i) => (
        <div key={i} className="qa">
          <ol>{a.questions.map((q, j) => <li key={j}>{q}</li>)}</ol>
          <p className="pre-wrap"><b>Answer</b> ({a.answered_by.slice(0, 8)}, {formatDate(a.answered_at)}): {a.answer}</p>
        </div>
      ))}
    </details>
  );
}

/* ============================ review ============================ */
export function DraftReview({ id }: { id: string }) {
  const { go } = useRouter();
  const draftQ = useAsync(useCallback(() => drafts.get(id), [id]));
  const settingsQ = useAsync(useCallback(() => drafts.reviewSettings(), []));
  const [filter, setFilter] = useState<'all' | Category>('all');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showGraph, setShowGraph] = useState(false);
  const [moved, setMoved] = useState<string | null>(null);
  const [rejections, setRejections] = useState<RejectedStatement[]>([]);
  const draft = dataOf(draftQ.state);
  const settings = settingsQ.state.status === 'ready' ? settingsQ.state.data : null;

  // Review settings change elsewhere (Settings, another tab): re-read them
  // when the window regains focus or Settings saves.
  const reloadSettings = settingsQ.reload;
  useEffect(() => {
    window.addEventListener('focus', reloadSettings);
    window.addEventListener('draft-review-settings-changed', reloadSettings);
    return () => { window.removeEventListener('focus', reloadSettings); window.removeEventListener('draft-review-settings-changed', reloadSettings); };
  }, [reloadSettings]);

  // Poll while an AI review runs.
  const running = draft?.review_assessment?.status === 'running';
  const reloadDraft = draftQ.reload;
  useEffect(() => {
    if (!running || busy) return;
    const t = setInterval(reloadDraft, 3000);
    return () => clearInterval(t);
  }, [running, busy, reloadDraft]);

  if (!draft) {
    if (draftQ.state.status === 'error') return <main className="page narrow"><LoadError error={draftQ.state.error} what="this draft" onRetry={reloadDraft} /></main>;
    return <main className="page narrow"><Loading what={`draft ${id}`} /></main>;
  }

  const run = async (label: string, action: () => Promise<unknown>, after?: () => void) => {
    setBusy(true); setError(null); setRejections([]);
    try { await action(); reloadDraft(); after?.(); return true; }
    catch (e) { setError(`${label} failed: ${errorMessage(e)}`); setRejections(rejectionsOf(e)); return false; }
    finally { setBusy(false); }
  };
  const decide = (action: 'approve' | 'reject' | 'withdraw', question: string) => {
    if (window.confirm(question)) void run(action[0].toUpperCase() + action.slice(1), () => drafts.act(id, action));
  };

  const ops = draft.ops;
  const active = isActive(draft);
  const pendingAliases = ops.some(op => op.kind === 'alias_suggestion' && op.payload.status === 'pending');
  const counts: Record<'all' | Category, number> = { all: ops.length, statements: 0, entities: 0, names: 0, links: 0, flagged: 0 };
  ops.forEach(o => { counts[categoryOf(o)]++; });
  const shown = ops.filter(o => filter === 'all' || categoryOf(o) === filter);
  const canRunReview = draft.status === 'submitted' && !!settings?.can_review && settings.mode !== 'off' && !running;

  return (
    <main className="page">
      <PageHeader eyebrow={<Link to={{ view: 'drafts' }}>← Drafts</Link>}
        title={draft.title || draft.id}
        blurb={<span className="mono small">{draft.id} · {ops.length} operation{ops.length === 1 ? '' : 's'} · created {formatDate(draft.created_at)}{draft.created_by ? ` by ${draft.created_by.slice(0, 8)}` : ''}</span>}
        actions={<span className={`status-badge ${draft.status}`}>{draft.status}</span>} />

      {draft.status === 'submitted' && <Notice>Submitted {relTime(draft.submitted_at)}. Nothing has reached the knowledge base yet: a curator approves or rejects it.</Notice>}
      {draft.status === 'approved' && <Notice tone="success">Approved {relTime(draft.decided_at)}. The operations were applied to the knowledge base.</Notice>}
      {(draft.status === 'rejected' || draft.status === 'withdrawn') && <Notice>{draft.status === 'rejected' ? 'Rejected' : 'Withdrawn'} {relTime(draft.decided_at)}. The draft is closed without applying its operations{ops.some(o => o.kind === 'alias_suggestion') ? '; aliases accepted earlier stay recorded in Names & aliases' : ''}.</Notice>}
      {pendingAliases && <Notice tone="warn">Decide each alias suggestion in <Link to={{ view: 'names' }}>Names &amp; aliases</Link> before approving or closing this draft. Automatic review stays advisory.</Notice>}
      {error && <Notice tone="error"><div>{error}{rejections.length > 0 && (
        <ul>{rejections.map((r, i) => (
          <li key={`${r.seq}-${i}`}><span className="mono">op {String(r.seq).padStart(2, '0')}</span>{r.text && <> “{r.text}”</>}: {r.reasons.join('; ')}</li>
        ))}</ul>
      )}</div></Notice>}
      {moved && <Notice tone="warn">{moved}</Notice>}
      {asksPerson(draft.review_assessment) && draft.review_assessment && draft.status === 'submitted' && (
        <ReviewerQuestion draftId={id} assessment={draft.review_assessment}
          onAnswered={() => { setMoved(null); reloadDraft(); }} onMoved={m => { setMoved(m); reloadDraft(); }} />
      )}
      {!!draft.review_assessment?.answers?.length && <PastAnswers answers={draft.review_assessment.answers} />}

      <div className="draft-grid">
        <div>
          <div className="filter-row" role="group" aria-label="Filter operations">
            {(['all', 'statements', 'entities', 'names', 'links', 'flagged'] as const).map(f => (
              <button key={f} className={`fchip${filter === f ? ' on' : ''}${f === 'flagged' ? ' flag' : ''}`} aria-pressed={filter === f} onClick={() => setFilter(f)}>
                {f}<span className="fc-ct">{counts[f]}</span>
              </button>
            ))}
            <span className="spacer" />
            {ops.length > 0 && <button className="btn ghost sm" aria-expanded={showGraph} onClick={() => setShowGraph(v => !v)}><I.graph width="14" height="14" />{showGraph ? 'Hide graph' : 'Show graph'}</button>}
          </div>
          {showGraph && <section className="card"><p className="muted small">The records this draft touches plus one hop of existing context. Drag, zoom and click as in the statement graph.</p><DraftGraph ops={ops} /></section>}
          {ops.length === 0 ? <EmptyState title="This draft is empty" blurb="Every operation was discarded." />
            : shown.length === 0 ? <p className="muted mono small">No operations match this filter.</p>
            : <div className="ops">{shown.map(op => (
              <OpCard key={op.seq} op={op} busy={busy} editable={active && op.kind !== 'alias_suggestion' && op.kind !== 'flag'}
                onDiscard={seq => void run('Discard', () => drafts.discardOp(id, seq))}
                onSave={(seq, payload) => run('Save', () => drafts.editOp(id, seq, payload))} />
            ))}</div>}
        </div>

        <aside className="rail">
          {active && (
            <div className="rail-sec">
              <div className="rs-label">Decide</div>
              <div className="stack-sm">
                {draft.status === 'open' && <button className="btn write" disabled={busy || !ops.length} onClick={() => void run('Submit', () => drafts.act(id, 'submit'))}><I.check width="15" height="15" />Submit for review</button>}
                <button className="btn primary" disabled={busy || pendingAliases} onClick={() => decide('approve', 'Approve this draft and apply its operations to the knowledge base?')}>Approve and apply</button>
                <button className="btn danger" disabled={busy || pendingAliases} onClick={() => decide('reject', 'Reject this draft? Its operations will not be applied.')}>Reject</button>
                <button className="btn ghost" disabled={busy || pendingAliases} onClick={() => decide('withdraw', 'Withdraw this draft? It closes without applying anything.')}>Withdraw</button>
              </div>
              <p className="hint">Approving and rejecting need the writer or admin role. Submitting hands an open draft to the curators.</p>
            </div>
          )}
          <div className="rail-sec">
            <div className="rs-label">AI review</div>
            {draft.review_assessment ? <AssessmentBadge assessment={draft.review_assessment} /> : <p className="muted small">Not reviewed yet.</p>}
            {draft.status === 'submitted' && (
              <div className="stack-sm">
                <button className="btn sm" disabled={busy || !canRunReview} onClick={() => void run('Review', () => drafts.act(id, 'review'))}>
                  {running ? 'Review running…' : draft.review_assessment ? 'Run review again' : 'Run review'}
                </button>
                <p className="hint">
                  {!settings ? 'Review settings are unavailable.'
                    : !settings.can_review ? 'Running a review needs a real curator role.'
                    : settings.mode === 'off' ? 'Automatic review is off.'
                    : `${settings.mode === 'review-only' ? 'Review only' : 'Review and apply'} · ${draftReviewProviderName(settings.provider)} · ${settings.model || 'no model configured'}.`}
                  {' '}<Link to={{ view: 'settings', section: 'review' }}>Draft review settings</Link>
                </p>
              </div>
            )}
          </div>
        </aside>
      </div>
      {draft.review_assessment && <AssessmentPanel assessment={draft.review_assessment} />}
      {!active && <p className="hint"><button className="link-btn" onClick={() => go({ view: 'drafts' })}>Back to all drafts</button></p>}
    </main>
  );
}

/* ============================ list ============================ */
type ListFilter = 'active' | 'completed' | 'all';

export function DraftsList() {
  const goIngest = useGoIngest();
  const { state, reload } = useAsync(useCallback(() => drafts.list(), []));
  const [filter, setFilter] = useState<ListFilter>('active');
  const list = dataOf(state);
  const running = !!list?.some(d => d.review_assessment?.status === 'running');
  useEffect(() => {
    if (!running) return;
    const t = setInterval(reload, 3000);
    return () => clearInterval(t);
  }, [running, reload]);

  // Drafts whose reviewer is waiting on a person come first.
  const sorted = [...(list || [])].sort((a, b) =>
    Number(asksPerson(b.review_assessment)) - Number(asksPerson(a.review_assessment)) || Date.parse(b.created_at) - Date.parse(a.created_at));
  const questions = sorted.filter(d => d.status === 'submitted' && asksPerson(d.review_assessment)).length;
  const open = sorted.filter(d => d.status === 'open');
  const submitted = sorted.filter(d => d.status === 'submitted');
  const activeCount = open.length + submitted.length;
  const shown = sorted.filter(d => filter === 'all' || (filter === 'active') === isActive(d));
  const filters: { id: ListFilter; label: string; count: number }[] = [
    { id: 'active', label: 'Active', count: activeCount },
    { id: 'completed', label: 'Completed', count: sorted.length - activeCount },
    { id: 'all', label: 'All', count: sorted.length },
  ];
  const summary: [number, string][] = [
    [questions, 'reviewer questions for you'],
    [submitted.length, 'awaiting a decision'],
    [open.length, 'open with their authors'],
    [open.reduce((n, d) => n + (d.op_count || 0), 0), 'operations in open drafts'],
  ];

  return (
    <main className="page narrow">
      <PageHeader eyebrow="Curate" title="Drafts"
        blurb="Every change from ingest, research, agents and drafters waits here. Open drafts are still with their authors; submitted drafts wait for a curator to approve or reject them."
        actions={<button className="ingest-btn" onClick={goIngest}><I.ingest width="15" height="15" />New from ingest</button>} />
      <div className="summary-cells">{summary.map(([n, l]) => <div key={l} className="sum-cell"><div className="sum-n">{n}</div><div className="sum-l">{l}</div></div>)}</div>
      <div className="filter-row" role="group" aria-label="Filter drafts">
        {filters.map(item => (
          <button key={item.id} className={`fchip${filter === item.id ? ' on' : ''}`} aria-pressed={filter === item.id} onClick={() => setFilter(item.id)}>
            {item.label}<span className="fc-ct">{item.count}</span>
          </button>
        ))}
        <span className="spacer" />
        <Link to={{ view: 'settings', section: 'review' }} className="btn ghost sm">Draft review settings</Link>
      </div>
      {state.status === 'error' && <LoadError error={state.error} what="drafts" onRetry={reload} />}
      {!list && state.status === 'loading' && <Loading what="drafts" />}
      {list && (sorted.length === 0
        ? <EmptyState title="No drafts yet" blurb="Ingest raw text or start research: every change stages here as a draft before it reaches the knowledge base." />
        : shown.length === 0
          ? <EmptyState title={`No ${filter} drafts`} blurb={filter === 'active' ? 'Nothing is open or waiting. Choose Completed or All to see closed drafts.' : 'Approved, rejected and withdrawn drafts appear here.'} />
          : <div className="row-list">{shown.map(d => <DraftRow key={d.id} d={d} />)}</div>)}
    </main>
  );
}

function DraftRow({ d }: { d: DraftSummary }): ReactNode {
  const ops = d.op_count || 0;
  return (
    <Link to={{ view: 'draft', id: d.id }} className="list-row">
      <span className={`dot ${d.status}`} />
      <span className="lr-body">
        <span className="lr-title">{d.title || d.id}</span>
        {d.review_assessment && <AssessmentBadge assessment={d.review_assessment} />}
        <span className="lr-meta"><span className="mono">{d.id}</span><span>·</span><span>{d.created_by ? d.created_by.slice(0, 8) : 'ingest'}</span><span>·</span><span>{ops} op{ops === 1 ? '' : 's'}</span></span>
      </span>
      <span className={`status-badge ${d.status}`}>{d.status}</span>
      <span className="lr-time">{relTime(d.created_at)}</span>
    </Link>
  );
}
