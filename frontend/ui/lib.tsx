// Shared primitives: icons, tags, statement text, page chrome, error boundary.
import { Component, createContext, useContext, useState, type ErrorInfo, type ReactNode, type SVGProps } from 'react';
import { editStatement, errorMessage, isAuthError, type Me } from './api';
import { layerOf, refreshStatement, substrate, type Entity, type Statement } from './data';
import { Link, useRouter } from './router';

/* ---------------- Substrate reload ----------------
   After a write that changes the dump, `refresh` reloads it and bumps
   `version` so screens that memoize over the index recompute. */
export const DataCtx = createContext<{ version: number; refresh: () => Promise<void> }>({ version: 0, refresh: async () => {} });
export const useDataCtx = () => useContext(DataCtx);

/* ---------------- Who is signed in (null until /api/me answers) ---------------- */
export const MeCtx = createContext<Me | null>(null);
export const useMe = () => useContext(MeCtx);

/* ---------------- Ingest launcher ----------------
   The shell owns the nonce that remounts Ingest when it is opened from Ingest. */
export const GoIngestCtx = createContext<() => void>(() => {});
export const useGoIngest = () => useContext(GoIngestCtx);

/* ---------------- Text ---------------- */
export function escapeRe(s: string) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

export function highlight(text: string, q: string): ReactNode {
  const terms = q.trim().split(/\s+/).filter(t => t.length > 1).map(escapeRe);
  if (!terms.length) return text;
  const re = new RegExp(`(${terms.join('|')})`, 'ig');
  return text.split(re).map((part, i) => i % 2 ? <mark key={i}>{part}</mark> : part);
}

export function relTime(iso: string | null | undefined): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(t)) return '';
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const formatDate = (iso: string | null | undefined) => iso ? new Date(iso).toLocaleString() : '—';

/* ---------------- Icons ---------------- */
type IconProps = SVGProps<SVGSVGElement>;
const svg = (p: IconProps, sw = 1.6) => ({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: sw, width: 16, height: 16, ...p });
export const I = {
  brand: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" {...p}>
      <circle cx="12" cy="12" r="2.4" fill="currentColor"/>
      <circle cx="5" cy="6" r="1.7" fill="currentColor" opacity="0.85"/>
      <circle cx="19" cy="7" r="1.7" fill="currentColor" opacity="0.85"/>
      <circle cx="4" cy="17" r="1.5" fill="currentColor" opacity="0.7"/>
      <circle cx="18" cy="18" r="1.9" fill="currentColor" opacity="0.7"/>
      <circle cx="12" cy="3.5" r="1.3" fill="currentColor" opacity="0.6"/>
      <path d="M12 12 L5 6 M12 12 L19 7 M12 12 L4 17 M12 12 L18 18 M12 12 L12 3.5" stroke="currentColor" strokeWidth="0.9" opacity="0.55"/>
      <path d="M5 6 L4 17 M19 7 L18 18" stroke="currentColor" strokeWidth="0.7" opacity="0.3"/>
    </svg>
  ),
  ask: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" width={16} height={16} {...p}>
      <path d="M12 3 C12 7 13 9 17 9 C13 9 12 11 12 15 C12 11 11 9 7 9 C11 9 12 7 12 3 Z" fill="currentColor"/>
      <circle cx="18.5" cy="16.5" r="2" fill="currentColor" opacity="0.6"/>
    </svg>
  ),
  find: (p: IconProps) => <svg {...svg(p, 1.8)}><circle cx="11" cy="11" r="6.5"/><path d="M16 16 L21 21" strokeLinecap="round"/></svg>,
  arrow: (p: IconProps) => <svg {...svg(p, 1.8)}><path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  semantic: (p: IconProps) => <svg {...svg(p)}><circle cx="7" cy="8" r="2.5"/><circle cx="17" cy="7" r="2"/><circle cx="15" cy="17" r="2.5"/><path d="M9 9.5 L15 15 M9 8 L15 7" opacity="0.5"/></svg>,
  grep: (p: IconProps) => <svg {...svg(p)}><path d="M4 7h16M4 12h10M4 17h13" strokeLinecap="round"/><rect x="13" y="9.5" width="6" height="5" rx="1" opacity="0.6"/></svg>,
  survey: (p: IconProps) => <svg {...svg(p)}><path d="M12 4 L12 9 M12 9 L6 14 M12 9 L18 14 M12 9 L12 14" opacity="0.7"/><circle cx="12" cy="3.5" r="1.8" fill="currentColor" stroke="none"/><circle cx="6" cy="15.5" r="1.8" fill="currentColor" stroke="none"/><circle cx="12" cy="15.5" r="1.8" fill="currentColor" stroke="none"/><circle cx="18" cy="15.5" r="1.8" fill="currentColor" stroke="none"/></svg>,
  gap: (p: IconProps) => <svg {...svg(p, 1.7)}><path d="M12 8v5M12 16.5v.01" strokeLinecap="round"/><path d="M10.3 4 L3.5 17 A1.5 1.5 0 0 0 5 19.2 H19 A1.5 1.5 0 0 0 20.5 17 L13.7 4 A1.5 1.5 0 0 0 10.3 4Z"/></svg>,
  prov: (p: IconProps) => <svg {...svg(p)}><path d="M9 7h8M9 12h8M9 17h5" strokeLinecap="round"/><circle cx="5" cy="7" r="1.3" fill="currentColor" stroke="none"/><circle cx="5" cy="12" r="1.3" fill="currentColor" stroke="none"/><circle cx="5" cy="17" r="1.3" fill="currentColor" stroke="none"/></svg>,
  trace: (p: IconProps) => <svg {...svg(p)}><circle cx="6" cy="6" r="2"/><circle cx="18" cy="12" r="2"/><circle cx="6" cy="18" r="2"/><path d="M8 6 H13 a3 3 0 0 1 3 3 v0 M16 12 H11 a3 3 0 0 0 -3 3 v0" opacity="0.6"/></svg>,
  interp: (p: IconProps) => <svg {...svg(p)}><circle cx="12" cy="12" r="8"/><path d="M9.5 9.8 a2.5 2.5 0 1 1 3.2 3 c-0.8 0.4-0.7 1.2-0.7 1.7M12 17.3v.01" strokeLinecap="round"/></svg>,
  check: (p: IconProps) => <svg {...svg(p, 2)}><path d="M5 12.5l4.5 4.5L19 7" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  warn: (p: IconProps) => <svg {...svg(p)}><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5M12 16v.01" strokeLinecap="round"/></svg>,
  timeout: (p: IconProps) => <svg {...svg(p)}><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2M9 3h6" strokeLinecap="round"/></svg>,
  empty: (p: IconProps) => <svg {...svg(p, 1.3)}><circle cx="12" cy="12" r="9" strokeDasharray="3 3"/><path d="M9 12h6" strokeLinecap="round"/></svg>,
  ingest: (p: IconProps) => <svg {...svg(p)}><path d="M12 3v10m0 0l-3.5-3.5M12 13l3.5-3.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" strokeLinecap="round"/></svg>,
  edit: (p: IconProps) => <svg {...svg(p, 1.7)}><path d="M4 20h4L18.6 9.4a2 2 0 0 0-2.83-2.83L5 17.2 4 20Z" strokeLinejoin="round"/><path d="M14 7l3 3" strokeLinecap="round"/></svg>,
  home: (p: IconProps) => <svg {...svg(p)}><path d="M4 11 12 4l8 7v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z" strokeLinejoin="round"/></svg>,
  table: (p: IconProps) => <svg {...svg(p)}><rect x="4" y="5" width="16" height="14" rx="2"/><path d="M4 10h16M10 10v9"/></svg>,
  graph: (p: IconProps) => <svg {...svg(p)}><circle cx="6" cy="7" r="2.2"/><circle cx="18" cy="6" r="2.2"/><circle cx="12" cy="17" r="2.2"/><path d="M8 8l3 7M16.5 7.5 13 15M8.2 7h7.6" opacity="0.7"/></svg>,
  hub: (p: IconProps) => <svg {...svg(p)}><path d="M12 4l7 4v8l-7 4-7-4V8z" strokeLinejoin="round"/><circle cx="12" cy="12" r="2.2"/></svg>,
  doc: (p: IconProps) => <svg {...svg(p)}><path d="M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" strokeLinejoin="round"/><path d="M14 3v5h5M9 13h6M9 17h6" strokeLinecap="round"/></svg>,
  research: (p: IconProps) => <svg {...svg(p)}><path d="M9 4h6M10 4v5l-5 9a1.5 1.5 0 0 0 1.3 2.2h11.4A1.5 1.5 0 0 0 19 18l-5-9V4" strokeLinejoin="round"/><path d="M7.5 14h9" opacity="0.6"/></svg>,
  tag: (p: IconProps) => <svg {...svg(p)}><path d="M4 12V5a1 1 0 0 1 1-1h7l8 8-8 8z" strokeLinejoin="round"/><circle cx="8.5" cy="8.5" r="1.3" fill="currentColor" stroke="none"/></svg>,
  book: (p: IconProps) => <svg {...svg(p)}><path d="M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z" strokeLinejoin="round"/><path d="M5 17a3 3 0 0 1 3-3h10" /></svg>,
  clock: (p: IconProps) => <svg {...svg(p)}><circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2" strokeLinecap="round"/></svg>,
  gear: (p: IconProps) => <svg {...svg(p)}><circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8" strokeLinecap="round"/></svg>,
  plug: (p: IconProps) => <svg {...svg(p)}><path d="M9 3v5M15 3v5M7 8h10v3a5 5 0 0 1-10 0zM12 16v5" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  menu: (p: IconProps) => <svg {...svg(p, 1.8)}><path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round"/></svg>,
  sun: (p: IconProps) => <svg {...svg(p)}><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" strokeLinecap="round"/></svg>,
  moon: (p: IconProps) => <svg {...svg(p)}><path d="M19 14.5A7.5 7.5 0 0 1 9.5 5a7.5 7.5 0 1 0 9.5 9.5z" strokeLinejoin="round"/></svg>,
};
export type IconName = keyof typeof I;

/* ---------------- Tags ---------------- */
// A statement kind, coloured by its layer (descriptive or prescriptive).
export function KindTag({ kind }: { kind: string }) {
  const def = substrate.vocab.statementKinds.find(k => k.name === kind);
  const layer = def ? def.layer : layerOf(kind);
  return (
    <span className={`kind layer-${layer}`} title={def?.gloss ? `${kind} · ${layer} · ${def.gloss}` : `${kind} · ${layer}`}>
      <span className="kg" />{kind}
    </span>
  );
}

// The record kind (entity, statement or name), as the graphs label nodes.
export function RecordTag({ kind }: { kind: string }) {
  return <span className={`rtag rt-${kind}`}><span className="rt-dot" />{kind}</span>;
}

export function LinkTag({ type, dir, hasWhen }: { type: string; dir?: 'in' | 'out'; hasWhen?: boolean }) {
  return (
    <span className={`lt${hasWhen ? ' has-when' : ''}`} title={hasWhen ? `${type} · gated by a when-condition` : type}>
      {dir && <span className="lt-dir">{dir === 'out' ? '→' : '←'}</span>}
      {type}{hasWhen && ' ⟂'}
    </span>
  );
}

export function EntityChip({ entity }: { entity: Entity }) {
  return <Link to={{ view: 'entity', id: entity.id }} className="echip" title={entity.description}>{entity.name}</Link>;
}

export function ScoreMeter({ score }: { score: number | null }) {
  if (score == null) return <span className="score lo"><span className="s-num">—</span></span>;
  const band = score >= 0.66 ? 'hi' : score >= 0.4 ? 'mid' : 'lo';
  return (
    <span className={`score ${band}`}>
      <span className="s-num">{score.toFixed(2)}</span>
      <span className="s-bar"><span className="s-fill" style={{ width: `${Math.max(4, score * 100)}%` }} /></span>
    </span>
  );
}

/* ---------------- Statement text with inline entity mentions ---------------- */
export function StatementText({ statement, className }: { statement: Pick<Statement, 'text' | 'mentions'>; className?: string }) {
  const idx = substrate.index;
  const { text } = statement;
  const surfaces: { surface: string; entity: Entity }[] = [];
  for (const id of statement.mentions || []) {
    const entity = idx.entities[id];
    if (!entity) continue;
    surfaces.push({ surface: entity.name, entity });
    for (const n of idx.namesByEntity[id] || []) surfaces.push({ surface: n.text, entity });
  }
  if (!surfaces.length) return <p className={className}>{text}</p>;
  surfaces.sort((a, b) => b.surface.length - a.surface.length);

  // Link each mentioned entity once, at its first occurrence.
  const re = new RegExp(`\\b(${surfaces.map(a => escapeRe(a.surface)).join('|')})\\b`, 'gi');
  const out: ReactNode[] = [];
  const used = new Set<string>();
  let last = 0;
  for (const m of text.matchAll(re)) {
    const at = m.index;
    if (at > last) out.push(text.slice(last, at));
    const found = surfaces.find(a => a.surface.toLowerCase() === m[0].toLowerCase());
    if (found && !used.has(found.entity.id)) {
      used.add(found.entity.id);
      out.push(<Link key={at} to={{ view: 'entity', id: found.entity.id }} className="mention">{m[0]}</Link>);
    } else {
      out.push(m[0]);
    }
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <p className={className}>{out}</p>;
}

/* ---------------- Editable statement text ----------------
   Saves through replace_text: writers and admins write live, drafters stage a
   draft op, and the result says which happened. */
type EditNote = { kind: 'saved' } | { kind: 'staged'; draftId: string };

function violationText(v: unknown): string {
  if (typeof v === 'string') return v;
  if (v && typeof v === 'object') {
    const r = v as { message?: unknown; rule?: unknown };
    if (typeof r.message === 'string') return r.message;
    if (typeof r.rule === 'string') return r.rule;
  }
  return JSON.stringify(v);
}

export function EditableStatementText({ statement, className, onSaved, compact, highlightQuery }: {
  statement: Pick<Statement, 'id' | 'text' | 'mentions'>; className?: string; onSaved?: () => void; compact?: boolean; highlightQuery?: string;
}) {
  const { go } = useRouter();
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(statement.text);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [violations, setViolations] = useState<unknown[] | null>(null);
  const [note, setNote] = useState<EditNote | null>(null);
  const [shown, setShown] = useState(statement);
  if (shown.id !== statement.id) { setShown(statement); setNote(null); setEditing(false); }

  const begin = () => { setVal(shown.text); setEditing(true); setErr(null); setViolations(null); setNote(null); };
  const cancel = () => { setEditing(false); setErr(null); setViolations(null); };

  const save = async (force: boolean) => {
    const text = val.trim();
    if (!text || busy) return;
    setBusy(true); setErr(null); setViolations(null);
    try {
      const res = await editStatement(statement.id, text, force);
      if (res.status === 'rejected') { setViolations(res.violations); return; }
      if (res.status === 'staged') { setEditing(false); setNote({ kind: 'staged', draftId: res.draftId }); onSaved?.(); return; }
      const fresh = await refreshStatement(statement.id);
      setShown(fresh || { ...shown, text });
      setEditing(false); setNote({ kind: 'saved' }); onSaved?.();
    } catch (e) {
      setErr(isAuthError(e) ? 'You need write access to edit statements.' : errorMessage(e, 'Save failed.'));
    } finally {
      setBusy(false);
    }
  };

  if (editing) {
    return (
      <div className="stmt-edit" onClick={e => e.stopPropagation()}>
        <textarea className="stmt-edit-area" value={val} autoFocus spellCheck={false} aria-label="Statement text"
          rows={compact ? 3 : 4} onChange={e => setVal(e.target.value)} />
        {violations && (
          <div className="notice warn">
            <I.warn width="15" height="15" />
            <div>
              <b>The phrasing check flagged this wording:</b>
              {violations.map((v, i) => <div key={i} className="mono small">— {violationText(v)}</div>)}
            </div>
          </div>
        )}
        {err && <p className="form-error" role="alert">{err}</p>}
        <div className="row gap-sm">
          <button className="btn primary sm" disabled={busy || !val.trim()} onClick={() => save(false)}>
            <I.check width="14" height="14" />{busy ? 'Saving…' : 'Save'}
          </button>
          {violations && <button className="btn sm" disabled={busy} onClick={() => save(true)} title="Save despite the phrasing-catalog warnings">Save anyway</button>}
          <button className="btn ghost sm" disabled={busy} onClick={cancel}>Cancel</button>
        </div>
      </div>
    );
  }

  return (
    <div className={`stmt-editable${compact ? ' compact' : ''}`}>
      {highlightQuery != null
        ? <p className={className}>{highlight(shown.text, highlightQuery)}</p>
        : <StatementText statement={shown} className={className} />}
      <div className="stmt-editable-foot" onClick={e => e.stopPropagation()}>
        <button className="stmt-edit-btn" onClick={begin} title="Edit this statement's text"><I.edit width="13" height="13" />edit</button>
        {note?.kind === 'saved' && <span className="stmt-edit-tag saved"><I.check width="12" height="12" />saved · re-embedded</span>}
        {note?.kind === 'staged' && (
          <button className="stmt-edit-tag staged" onClick={() => go({ view: 'draft', id: note.draftId })}>
            <I.prov width="12" height="12" />staged in a draft → review
          </button>
        )}
      </div>
    </div>
  );
}

/* ---------------- Page chrome ---------------- */
export function PageHeader({ eyebrow, title, blurb, actions }: {
  eyebrow?: ReactNode; title: ReactNode; blurb?: ReactNode; actions?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className="page-head-text">
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {blurb && <p className="page-blurb">{blurb}</p>}
      </div>
      {actions && <div className="page-head-actions">{actions}</div>}
    </header>
  );
}

export function Card({ title, actions, children, className = '' }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && <header className="card-head">{title && <h2>{title}</h2>}{actions && <div className="row gap-sm">{actions}</div>}</header>}
      {children}
    </section>
  );
}

export function EmptyState({ title, blurb, children }: { title: ReactNode; blurb?: ReactNode; children?: ReactNode }) {
  return (
    <div className="empty">
      <I.empty className="e-glyph" />
      <div className="e-title">{title}</div>
      {blurb && <div className="e-blurb">{blurb}</div>}
      {children && <div className="e-actions">{children}</div>}
    </div>
  );
}

// An inline status line: `error` and `warn` announce as alerts.
export function Notice({ tone = 'info', children }: { tone?: 'info' | 'success' | 'warn' | 'error'; children: ReactNode }) {
  return <div className={`notice ${tone}`} role={tone === 'error' || tone === 'warn' ? 'alert' : 'status'}>{children}</div>;
}

export function LoadError({ error, what, onRetry }: { error: unknown; what: string; onRetry?: () => void }) {
  const unauth = isAuthError(error);
  return (
    <Notice tone="error">
      <span>{unauth ? `Your account cannot load ${what}.` : `Could not load ${what}: ${errorMessage(error)}`}</span>
      {onRetry && !unauth && <button className="btn sm" onClick={onRetry}>Retry</button>}
    </Notice>
  );
}

export const Loading = ({ what }: { what: string }) => <p className="muted mono small" role="status">Loading {what}…</p>;

/* ---------------- Error boundary ----------------
   Contains a crash to the screen that threw, so the shell and navigation stay
   usable. The shell keys it by route, so navigating away clears the error. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error(error, info.componentStack); }
  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <main className="page narrow" role="alert">
        <EmptyState title="This screen failed to render"
          blurb={`${error.message || String(error)}. The rest of the app still works — go back or pick another screen.`} />
      </main>
    );
  }
}

