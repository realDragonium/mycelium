// Every HTTP call the app makes goes through `request`, which throws an
// HttpError carrying the server's `detail` on any non-2xx response, or a
// human message for the status when the server sent none. A network failure
// is an HttpError with status 0.
//
// The generic parameter on the helpers is the caller's statement of what the
// endpoint returns; nothing checks it at runtime, so keep each one next to the
// endpoint it describes.

export class HttpError extends Error {
  readonly status: number;
  readonly path: string;
  // The server's `detail` as sent, for endpoints that return more than a message.
  readonly detail: unknown;
  readonly body: unknown;
  constructor(message: string, status: number, path: string, detail: unknown = null, body: unknown = null) {
    super(message);
    this.status = status;
    this.path = path;
    this.detail = detail;
    this.body = body;
  }
}

export function errorMessage(error: unknown, fallback = 'The request failed. Try again.'): string {
  if (error instanceof Error && error.message) return error.message;
  return typeof error === 'string' && error ? error : fallback;
}

export const isAuthError = (error: unknown) => error instanceof HttpError && (error.status === 401 || error.status === 403);

function detailOf(body: unknown): string | null {
  if (!body || typeof body !== 'object' || !('detail' in body)) return null;
  const { detail } = body;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') return detail.message;
  return null;
}

function statusMessage(status: number): string {
  if (status === 0) return 'Could not reach the server. Check your connection and try again.';
  if (status === 401) return 'You are signed out. Sign in and try again.';
  if (status === 403) return 'You do not have permission to do this.';
  if (status === 404) return 'Not found. It may have been moved or deleted.';
  if (status === 405) return 'This action is not allowed here.';
  if (status === 409) return 'This changed in the meantime. Reload and try again.';
  if (status === 413) return 'That is too large to send.';
  if (status === 400 || status === 422) return 'The server did not accept the request. Check the values and try again.';
  if (status === 429) return 'Too many requests. Wait a moment and try again.';
  if (status >= 500) return 'The server ran into a problem. Try again shortly.';
  return `The request failed (status ${status}). Try again.`;
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { accept: 'application/json' };
  if (body !== undefined) headers['content-type'] = 'application/json';
  let res: Response;
  try {
    res = await fetch(path, {
      method, headers, signal, credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new HttpError(statusMessage(0), 0, path);
  }
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try { parsed = JSON.parse(text); } catch { parsed = text; }
  }
  if (!res.ok) throw new HttpError(detailOf(parsed) || statusMessage(res.status), res.status, path, parsed && typeof parsed === 'object' && 'detail' in parsed ? parsed.detail : null, parsed);
  return parsed as T;
}

export const getJSON = <T>(path: string, signal?: AbortSignal) => request<T>('GET', path, undefined, signal);
export const postJSON = <T>(path: string, body: unknown = {}, signal?: AbortSignal) => request<T>('POST', path, body, signal);
export const patchJSON = <T>(path: string, body: unknown) => request<T>('PATCH', path, body);
export const putJSON = <T>(path: string, body: unknown) => request<T>('PUT', path, body);
export const deleteJSON = <T>(path: string, body?: unknown) => request<T>('DELETE', path, body);

export const enc = encodeURIComponent;

/* ------------------------------ identity ------------------------------ */
export type Role = 'reader' | 'drafter' | 'writer' | 'admin';
export interface Me {
  id: string; name: string; role: Role; type: string; auth_enabled: boolean;
  audience_id: string | null;
  audience: { id: string; name: string; scope: 'internal' | 'external' } | null;
}
export const isScoped = (me: Pick<Me, 'audience_id'> | null | undefined) => me?.audience_id != null;
export const getMe = () => getJSON<Me>('/api/me');
export interface SubstrateCounts { statements: number; entities: number; names: number; links: number; entity_links: number }
export const getSubstrateCounts = () => getJSON<SubstrateCounts>('/api/substrate-counts');
// `partial_restore` names the databases startup found missing beside a
// populated substrate; it is fixed for the life of the server process.
export interface ServerInfo { partial_restore: string[] }
export const getServerInfo = () => getJSON<ServerInfo>('/api/server-info');

/* -------------------------------- Find -------------------------------- */
export type FindMode = 'semantic' | 'grep' | 'survey';
export const FIND_MODES: readonly FindMode[] = ['semantic', 'grep', 'survey'];
export const isFindMode = (value: string): value is FindMode => (FIND_MODES as readonly string[]).includes(value);

export interface FindRow {
  id: string; kind: string; text: string;
  // Semantic and survey rows carry a relevance score; grep is literal and
  // reports how it matched and how often instead.
  score: number | null;
  via: string | null;
  occurrences: number;
}
export interface EntityHit { id: string; name: string; matched_name: string; description: string; score: number | null }

interface RawScored { id?: string; kind: string; text: string; score?: number | null }
interface RawGrep { statements?: { id: string; kind: string; text: string; matched_via?: string }[] }

export async function findStatements(mode: FindMode, query: string, signal?: AbortSignal): Promise<FindRow[]> {
  const q = query.trim();
  if (!q) return [];
  if (mode === 'grep') {
    const res = await postJSON<RawGrep>('/grep-statements', { query: q, limit: 80 }, signal);
    const needle = q.toLowerCase();
    const rows = (res.statements || []).map((s): FindRow => {
      const hay = s.text.toLowerCase();
      let n = 0;
      for (let i = hay.indexOf(needle); i !== -1; i = hay.indexOf(needle, i + needle.length)) n++;
      return { id: s.id, kind: s.kind, text: s.text, score: null, via: s.matched_via || null, occurrences: n };
    });
    // Text hits first, alias-only hits after.
    return rows.sort((a, b) => b.occurrences - a.occurrences);
  }
  const list = mode === 'survey'
    ? await postJSON<RawScored[]>('/survey-statements', { query: q, k: 6 }, signal)
    : await postJSON<RawScored[]>('/search-statements', { query: q, limit: 14 }, signal);
  return (Array.isArray(list) ? list : [])
    // Depth expansions come back unscored; Find shows direct hits only.
    .filter((s): s is RawScored & { id: string; score: number } => !!s.id && typeof s.score === 'number')
    .map(s => ({ id: s.id, kind: s.kind, text: s.text, score: s.score, via: null, occurrences: 0 }))
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
}

export async function searchEntities(query: string, signal?: AbortSignal): Promise<EntityHit[]> {
  const res = await postJSON<{ entities?: EntityHit[] }>('/search-entities', { query, k: 6, min_score: 0.5 }, signal);
  return res.entities || [];
}

/* -------------------------- statement edits --------------------------- */
// replace_text writes live for writers and admins and stages a draft op for
// drafters; `force` retries past a phrasing-catalog rejection.
export type EditResult =
  | { status: 'saved' }
  | { status: 'staged'; draftId: string }
  | { status: 'rejected'; violations: unknown[] };

interface RawReplaceText { rejected?: boolean; violations?: unknown[]; draft_id?: string; queued?: boolean }
export async function editStatement(id: string, text: string, force: boolean): Promise<EditResult> {
  const raw = await postJSON<RawReplaceText | null>('/replace-text', { id, text, allow_phrasing_violations: force });
  if (raw?.rejected) return { status: 'rejected', violations: raw.violations || [] };
  if (raw?.draft_id && raw.queued) return { status: 'staged', draftId: raw.draft_id };
  return { status: 'saved' };
}

/* -------------------------------- write ------------------------------- */
// Creating an entity or attaching an alias enqueues a mention rescan, so
// statements containing the new name pick up the mention on the next drain.
export const upsertEntity = (name: string, description: string) => postJSON<{ entity_id: string }>('/upsert-entity', { name, description });
export const upsertName = (text: string, entityId: string) => postJSON<unknown>('/upsert-name', { text, entity_id: entityId });

// Alias suggestions land in their own, already-submitted draft, so one ingest
// can produce two drafts.
export type IngestResult =
  | { outcome: 'draft_created'; draft_id: string; alias_draft_id?: string | null; submitted_for_review?: boolean; ops?: unknown[] }
  | { outcome: 'nothing_to_ingest'; reason?: string };

/* ---------------------------- review mode ----------------------------- */
// Whether drafts from ingest go straight to the AI reviewer, and
// whether an accepted review applies without a person.
export type ReviewMode = 'off' | 'review-only' | 'review-and-apply';
export const getReviewMode = () => getJSON<{ mode: ReviewMode }>('/api/draft-review/settings').then(r => r.mode);
export const ingest = (text: string) => postJSON<IngestResult>('/ingest', { text });

/* ---------------------------- knowledge gaps --------------------------- */
export type GapStatus = 'open' | 'resolved' | 'dismissed';
export type GapAction = 'resolve' | 'dismiss' | 'reopen';
export interface KnowledgeGap {
  id: string; text: string; status: GapStatus;
  created_at: string; created_by: string | null;
  resolved_at: string | null; dismissed_at: string | null;
  // What the report came from, when the reporter named it.
  draft_id: string | null; statement_id: string | null; document_id: string | null;
}
export const knowledgeGaps = {
  // can_write: whether the caller may resolve, dismiss or reopen a report.
  list: () => getJSON<{ gaps: KnowledgeGap[]; can_write: boolean }>('/api/knowledge-gaps'),
  update: (id: string, action: GapAction) => patchJSON<{ gap: KnowledgeGap }>(`/api/knowledge-gaps/${enc(id)}`, { action }).then(r => r.gap),
  report: (text: string) => postJSON<unknown>('/report-knowledge-gap', { text }),
};

/* -------------------------- names workspace -------------------------- */
export type NameActionKind = 'add' | 'correct' | 'prefer' | 'move' | 'split' | 'merge' | 'remove';
export type NameAction =
  | { kind: 'add'; entity_id: string; text: string }
  | { kind: 'correct'; entity_id: string; name_id: string; text: string }
  | { kind: 'prefer'; entity_id: string; name_id: string }
  | { kind: 'move'; entity_id: string; name_id: string; target_entity_id: string }
  | { kind: 'split'; entity_id: string; name_ids: string[]; preferred_name_id: string; description: string }
  | { kind: 'merge'; entity_id: string; target_entity_id: string; preferred_name_id: string; description: string }
  | { kind: 'remove'; entity_id: string; name_id: string };

export interface WorkspaceName { id: string; text: string; generated_from_name_id: string | null }
export interface WorkspaceConcept {
  id: string; description: string; preferred_name_id: string | null;
  label: string; names: WorkspaceName[];
}
export interface NamesCatalogue {
  revision: string; entities: WorkspaceConcept[]; can_write: boolean; allowed_actions: NameActionKind[];
}
export interface NamesExample { id: string; kind: string; text: string }
export interface NamesRelationship { source: string; target: string; link_type: string }
export interface NamesHistory {
  at: string; actor: string | null; op: string; target_id: string;
  before_json: string | null; after_json: string | null; context_json: string | null;
}
export interface NamesDetail {
  revision: string; entity: WorkspaceConcept; examples: NamesExample[]; example_count: number;
  relationships: NamesRelationship[]; history: NamesHistory[]; history_available: boolean;
}
export interface NamesPreview {
  revision: string; action: NameAction; summary: string; names: WorkspaceName[];
  examples: NamesExample[]; example_count: number;
  relationships_before: NamesRelationship[]; relationships_after: NamesRelationship[]; warnings: string[];
}
export interface NamesApplied { entity_id: string; revision: string; documents_unanchored: number }
export interface MentionCandidate {
  statement_id: string; text: string; kind: string;
  names: { name_id: string; text: string }[];
  match: 'derived' | 'approved' | 'possible';
}
export interface MentionCandidatePage {
  matches: MentionCandidate[]; next_after: number; has_more: boolean; scanned: number;
}

export interface DuplicateMatch { a_name: string; b_name: string; via: 'fold' | 'same_words' | 'initials' | 'embedding'; score: number }
export interface DuplicateCandidate { a_entity_id: string; b_entity_id: string; score: number; matches: DuplicateMatch[] }
export interface DuplicatePage { candidates: DuplicateCandidate[]; total: number }
export interface DismissedDuplicate { a_entity_id: string; b_entity_id: string; dismissed_at: string; dismissed_by: string | null }

export const namesWorkspace = {
  catalogue: (signal?: AbortSignal) => getJSON<NamesCatalogue>('/api/names-workspace', signal),
  detail: (id: string, signal?: AbortSignal) => getJSON<NamesDetail>(`/api/names-workspace/${enc(id)}`, signal),
  preview: (action: NameAction) => postJSON<NamesPreview>('/api/names-workspace/preview', { action }),
  apply: (action: NameAction, expectedRevision: string) => postJSON<NamesApplied>('/api/names-workspace/apply', { action, expected_revision: expectedRevision }),
  mentionCandidates: (entityId: string, after: number, signal?: AbortSignal) =>
    getJSON<MentionCandidatePage>(`/api/mention-candidates?${new URLSearchParams({ entity_id: entityId, after: String(after), limit: '30' })}`, signal),
  duplicates: (limit: number, signal?: AbortSignal) => postJSON<DuplicatePage>('/find-entity-duplicates', { limit }, signal),
  dismissDuplicate: (a: string, b: string) => postJSON<null>('/api/names-workspace/duplicates/dismiss', { a_entity_id: a, b_entity_id: b }),
  dismissedDuplicates: (signal?: AbortSignal) => getJSON<{ dismissed: DismissedDuplicate[] }>('/api/names-workspace/duplicates/dismissed', signal),
  restoreDuplicate: (a: string, b: string) => postJSON<null>('/api/names-workspace/duplicates/restore', { a_entity_id: a, b_entity_id: b }),
};

/* ----------------------------- activity ------------------------------ */
export interface ActivityEvent {
  event_id: string | number;
  at: string;
  actor: string | null;
  op: string;
  target_kind: string;
  target_id: string;
}
export interface ActivityResponse { events: ActivityEvent[]; total: number; limit: number; offset: number }
export const getActivity = (query: URLSearchParams) => getJSON<ActivityResponse>(`/api/history?${query.toString()}`);

/* -------------------------------- Ask --------------------------------- */
export type Confidence = 'high' | 'medium' | 'low';
export interface RawAnswered {
  outcome: 'answered';
  answer: string;
  confidence: Confidence;
  interpretation: { as_asked?: string; resolved_to?: string; reframed?: boolean; reframe_reason?: string };
  gaps: string[];
  provenance: string[];
  trace?: AskTrace;
}
export interface RawClarification {
  outcome: 'needs_clarification';
  question: string;
  candidates: { interpretation?: string; would_pull?: string | string[] }[];
  known_so_far?: string | string[];
}
export interface AskTrace {
  question?: string; model?: string; op_count?: number;
  tool_calls?: { name?: string }[];
  sub_question_ledger?: { sub_question: string; status?: string }[];
  degraded?: boolean; forced_finalize?: boolean;
}
export type AskResult = RawAnswered | RawClarification;
export type AskEvent =
  | { type: 'progress'; message: string }
  | { type: 'answer_delta'; text: string }
  | { type: 'answer_reset' };

function completedAsk(raw: unknown): AskResult {
  const r = raw as Partial<Omit<RawAnswered, 'outcome'>> & Partial<Omit<RawClarification, 'outcome'>> & { outcome?: string; detail?: string } | null;
  if (!r || (r.outcome !== 'answered' && r.outcome !== 'needs_clarification')) {
    throw new Error(r?.detail || 'Ask returned no complete result.');
  }
  if (r.outcome === 'answered' && (typeof r.answer !== 'string' || !['high', 'medium', 'low'].includes(r.confidence || '')
      || !Array.isArray(r.provenance) || !Array.isArray(r.gaps) || !r.interpretation)) throw new Error('Ask returned an invalid answer.');
  if (r.outcome === 'needs_clarification' && (typeof r.question !== 'string' || !Array.isArray(r.candidates)
      || r.candidates.length < 2)) throw new Error('Ask returned an invalid clarification.');
  return r as AskResult;
}

async function readAskStream(res: Response, onEvent: (event: AskEvent) => void, signal: AbortSignal): Promise<AskResult> {
  if (!res.body) throw new Error('This browser cannot read the Ask stream.');
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (signal.aborted) throw new DOMException('Ask cancelled.', 'AbortError');
      buffer = (buffer + decoder.decode(value, { stream: !done })).replace(/\r\n/g, '\n');
      for (let boundary = buffer.indexOf('\n\n'); boundary >= 0; boundary = buffer.indexOf('\n\n')) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
        if (!data) continue;
        const event = JSON.parse(data) as { type?: string; result?: unknown; message?: string; text?: unknown };
        if (event.type === 'complete') return completedAsk(event.result);
        if (event.type === 'error') throw new Error(event.message || 'Ask failed.');
        if (event.type === 'cancelled') throw new DOMException('Ask cancelled.', 'AbortError');
        if (event.type === 'progress') onEvent({ type: 'progress', message: event.message || '' });
        if (event.type === 'answer_reset') onEvent({ type: 'answer_reset' });
        if (event.type === 'answer_delta') {
          if (typeof event.text !== 'string') throw new Error('Invalid Ask answer delta.');
          onEvent({ type: 'answer_delta', text: event.text });
        }
      }
      if (done) throw new Error('The connection ended before Ask completed. Any text shown is incomplete.');
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export async function ask(question: string, signal: AbortSignal, onEvent: (event: AskEvent) => void): Promise<AskResult> {
  const res = await fetch('/ask', {
    method: 'POST', credentials: 'same-origin', signal,
    headers: { accept: 'text/event-stream', 'content-type': 'application/json' },
    body: JSON.stringify({ question, verbose: true }),
  });
  if (!res.ok) {
    let detail = statusMessage(res.status);
    try { detail = detailOf(await res.json()) || detail; } catch { /* non-JSON body */ }
    throw new HttpError(detail, res.status, '/ask');
  }
  return (res.headers.get('content-type') || '').includes('text/event-stream')
    ? readAskStream(res, onEvent, signal)
    : completedAsk(await res.json());
}

/* --------------------------- knowledge health -------------------------- */
export type StatementFilter = 'isolated' | 'unmentioned' | 'unlabelled';
export type EntityFilter = 'undescribed' | 'unused';
export type HealthList = StatementFilter | EntityFilter;
export const STATEMENT_FILTERS: readonly StatementFilter[] = ['isolated', 'unmentioned', 'unlabelled'];
export const HEALTH_LISTS: readonly HealthList[] = [...STATEMENT_FILTERS, 'undescribed', 'unused'];
export const isHealthList = (value: string): value is HealthList => (HEALTH_LISTS as readonly string[]).includes(value);
export const isStatementFilter = (value: HealthList): value is StatementFilter => (STATEMENT_FILTERS as readonly string[]).includes(value);

export interface HealthCounts {
  statements: number; entities: number;
  isolated: number; unmentioned: number; undescribed: number; unused: number;
  unlabelled: number; labelling_failed: number;
  open_gaps: number; pending_drafts: number; out_of_date_documents: number;
}
// `priced` is false when the model has no known price: then neither the
// cost nor the spending cap applies.
export interface ConnectLimits { batch_size: number; max_cost_usd: number; provider: string; model: string; priced: boolean }
export interface HealthView { counts: HealthCounts; connect: ConnectLimits | null; connect_error: string | null }
export interface HealthStatement {
  id: string; kind: string; text: string; links: number; mentions: string[];
  label_error: string | null; in_pending_draft: boolean;
}
export interface HealthEntity { id: string; name: string | null; description: string | null }
export interface Page<T> { items: T[]; next_after: string | null }
export type ConnectResult = IngestResult & { cost_usd: number | null; flagged?: string[] };

export const knowledgeHealth = {
  view: () => getJSON<HealthView>('/api/knowledge-health'),
  statements: (which: StatementFilter, params: { after?: string | null; limit?: number; skipPending?: boolean } = {}) => {
    const qs = new URLSearchParams({ limit: String(params.limit ?? 50) });
    if (params.after) qs.set('after', params.after);
    if (params.skipPending) qs.set('skip_pending', 'true');
    return getJSON<Page<HealthStatement>>(`/api/knowledge-health/statements/${which}?${qs}`);
  },
  entities: (which: EntityFilter, after?: string | null) =>
    getJSON<Page<HealthEntity>>(`/api/knowledge-health/entities/${which}?${new URLSearchParams(after ? { after } : {})}`),
  connect: (statementIds: string[]) => postJSON<ConnectResult>('/connect-statements', { statement_ids: statementIds }),
};
