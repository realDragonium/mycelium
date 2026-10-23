// Every HTTP call the app makes goes through `request`, which throws an
// HttpError carrying the server's `detail` on any non-2xx response.
//
// The generic parameter on the helpers is the caller's statement of what the
// endpoint returns; nothing checks it at runtime, so keep each one next to the
// endpoint it describes.

export class HttpError extends Error {
  readonly status: number;
  readonly path: string;
  // The server's `detail` as sent, for endpoints that return more than a message.
  readonly detail: unknown;
  constructor(message: string, status: number, path: string, detail: unknown = null) {
    super(message);
    this.status = status;
    this.path = path;
    this.detail = detail;
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
  return detail == null ? null : JSON.stringify(detail);
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { accept: 'application/json' };
  if (body !== undefined) headers['content-type'] = 'application/json';
  const res = await fetch(path, {
    method, headers, signal, credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try { parsed = JSON.parse(text); } catch { parsed = text; }
  }
  if (!res.ok) throw new HttpError(detailOf(parsed) || `${res.status} ${res.statusText}`.trim(), res.status, path, parsed && typeof parsed === 'object' && 'detail' in parsed ? parsed.detail : null);
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
export interface Me { id: string; name: string; role: Role; type: string; auth_enabled: boolean }
export const getMe = () => getJSON<Me>('/api/me');
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
// Whether drafts from ingest and research go straight to the AI reviewer, and
// whether an accepted review applies without a person.
export type ReviewMode = 'off' | 'review-only' | 'review-and-apply';
export const getReviewMode = () => getJSON<{ mode: ReviewMode }>('/api/draft-review/settings').then(r => r.mode);
export const ingest = (text: string) => postJSON<IngestResult>('/ingest', { text });

/* ------------------------------ research ------------------------------ */
export interface ResearchRun {
  id: string; topic: string | null; source: string | null; status: string;
  created_at: string; finished_at: string | null; draft_id: string | null; error: string | null;
}
export interface ResearchSource { name: string }
export const research = {
  start: (topic: string, source: string) => postJSON<unknown>('/start-research', { topic, source }),
  list: () => getJSON<{ runs?: ResearchRun[] }>('/list-research-runs').then(r => r.runs || []),
  sources: () => getJSON<{ sources?: ResearchSource[] }>('/list-research-sources').then(r => r.sources || []),
};

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
  list: () => getJSON<{ gaps: KnowledgeGap[] }>('/api/knowledge-gaps').then(r => r.gaps),
  update: (id: string, action: GapAction) => patchJSON<{ gap: KnowledgeGap }>(`/api/knowledge-gaps/${enc(id)}`, { action }).then(r => r.gap),
  report: (text: string) => postJSON<unknown>('/report-knowledge-gap', { text }),
};

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
    let detail = `${res.status} ${res.statusText}`;
    try { detail = detailOf(await res.json()) || detail; } catch { /* non-JSON body */ }
    throw new HttpError(detail, res.status, '/ask');
  }
  return (res.headers.get('content-type') || '').includes('text/event-stream')
    ? readAskStream(res, onEvent, signal)
    : completedAsk(await res.json());
}
