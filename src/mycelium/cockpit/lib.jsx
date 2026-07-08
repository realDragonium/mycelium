// lib.jsx — shared helpers, icons, primitives, router context.
const { useState, useEffect, useMemo, useRef, useCallback, createContext, useContext, Fragment } = React;

/* ---------------- Index ---------------- */
function buildIndex(data) {
  const byId = {};
  data.entities.forEach(e => { byId[e.id] = { ...e, _kind: 'entity' }; });
  data.statements.forEach(s => { byId[s.id] = { ...s, _kind: 'statement' }; });
  data.names.forEach(n => { byId[n.id] = { ...n, _kind: 'name' }; });

  const outgoing = {}, incoming = {};
  data.links.forEach(l => {
    (outgoing[l.from] = outgoing[l.from] || []).push(l);
    (incoming[l.to] = incoming[l.to] || []).push(l);
  });

  const namesByEntity = {};
  data.names.forEach(n => { (namesByEntity[n.entity] = namesByEntity[n.entity] || []).push(n); });

  const mentionsByEntity = {};
  data.statements.forEach(s => (s.mentions || []).forEach(eid => {
    (mentionsByEntity[eid] = mentionsByEntity[eid] || []).push(s);
  }));

  const kindLayer = {};
  data.statementKinds.forEach(k => { kindLayer[k.name] = k; });

  return { byId, outgoing, incoming, namesByEntity, mentionsByEntity, kindLayer };
}

/* ---------------- Router ---------------- */
const RouterCtx = createContext(null);
const useRouter = () => useContext(RouterCtx);

function parseHash() {
  const h = window.location.hash.replace(/^#/, '');
  if (!h || h === '/') return { view: 'landing' };
  const [path, qs] = h.split('?');
  const parts = path.split('/').filter(Boolean);
  const p = Object.fromEntries(new URLSearchParams(qs || ''));
  if (parts[0] === 'find') return { view: 'find', query: p.q || '', mode: p.mode || 'semantic' };
  if (parts[0] === 'ask') return { view: 'ask', query: p.q || '' };
  if (parts[0] === 'ingest') return { view: 'ingest' };
  if (parts[0] === 'research') return { view: 'research' };
  if (parts[0] === 'coverage') return { view: 'coverage' };
  if (parts[0] === 'mentions') return { view: 'mentions' };
  if (parts[0] === 'drafts') return { view: 'drafts' };
  if (parts[0] === 'draft' && parts[1]) return { view: 'draft', id: parts[1] };
  if (parts[0] === 's' && parts[1]) return { view: 'statement', id: parts[1] };
  if (parts[0] === 'e' && parts[1]) return { view: 'entity', id: parts[1] };
  return { view: 'landing' };
}
function routeToHash(n) {
  if (n.view === 'find') return `#/find?q=${encodeURIComponent(n.query || '')}&mode=${n.mode || 'semantic'}`;
  if (n.view === 'ask') return `#/ask?q=${encodeURIComponent(n.query || '')}`;
  if (n.view === 'ingest') return '#/ingest';
  if (n.view === 'research') return '#/research';
  if (n.view === 'coverage') return '#/coverage';
  if (n.view === 'mentions') return '#/mentions';
  if (n.view === 'drafts') return '#/drafts';
  if (n.view === 'draft') return `#/draft/${n.id}`;
  if (n.view === 'statement') return `#/s/${n.id}`;
  if (n.view === 'entity') return `#/e/${n.id}`;
  return '#/';
}

/* ---------------- Text utils ---------------- */
function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function highlight(text, q) {
  if (!q || !q.trim()) return text;
  const terms = q.trim().split(/\s+/).filter(t => t.length > 1).map(escapeRe);
  if (!terms.length) return text;
  const re = new RegExp(`(${terms.join('|')})`, 'ig');
  const parts = String(text).split(re);
  return parts.map((p, i) => re.test(p) ? <mark key={i}>{p}</mark> : <span key={i}>{p}</span>);
}

/* ---------------- Icons ---------------- */
const I = {
  brand: (p) => (
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
  ask: (p) => (
    <svg viewBox="0 0 24 24" fill="none" {...p}>
      <path d="M12 3 C12 7 13 9 17 9 C13 9 12 11 12 15 C12 11 11 9 7 9 C11 9 12 7 12 3 Z" fill="currentColor"/>
      <circle cx="18.5" cy="16.5" r="2" fill="currentColor" opacity="0.6"/>
    </svg>
  ),
  find: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...p}>
      <circle cx="11" cy="11" r="6.5"/><path d="M16 16 L21 21" strokeLinecap="round"/>
    </svg>
  ),
  arrow: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...p}><path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round"/></svg>),
  semantic: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" {...p}><circle cx="7" cy="8" r="2.5"/><circle cx="17" cy="7" r="2"/><circle cx="15" cy="17" r="2.5"/><path d="M9 9.5 L15 15 M9 8 L15 7" opacity="0.5"/></svg>),
  grep: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" {...p}><path d="M4 7h16M4 12h10M4 17h13" strokeLinecap="round"/><rect x="13" y="9.5" width="6" height="5" rx="1" opacity="0.6"/></svg>),
  survey: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" {...p}><path d="M12 4 L12 9 M12 9 L6 14 M12 9 L18 14 M12 9 L12 14" opacity="0.7"/><circle cx="12" cy="3.5" r="1.8" fill="currentColor" stroke="none"/><circle cx="6" cy="15.5" r="1.8" fill="currentColor" stroke="none"/><circle cx="12" cy="15.5" r="1.8" fill="currentColor" stroke="none"/><circle cx="18" cy="15.5" r="1.8" fill="currentColor" stroke="none"/></svg>),
  gap: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" {...p}><path d="M12 8v5M12 16.5v.01" strokeLinecap="round"/><path d="M10.3 4 L3.5 17 A1.5 1.5 0 0 0 5 19.2 H19 A1.5 1.5 0 0 0 20.5 17 L13.7 4 A1.5 1.5 0 0 0 10.3 4Z"/></svg>),
  prov: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" {...p}><path d="M9 7h8M9 12h8M9 17h5" strokeLinecap="round"/><circle cx="5" cy="7" r="1.3" fill="currentColor" stroke="none"/><circle cx="5" cy="12" r="1.3" fill="currentColor" stroke="none"/><circle cx="5" cy="17" r="1.3" fill="currentColor" stroke="none"/></svg>),
  trace: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" {...p}><circle cx="6" cy="6" r="2"/><circle cx="18" cy="12" r="2"/><circle cx="6" cy="18" r="2"/><path d="M8 6 H13 a3 3 0 0 1 3 3 v0 M16 12 H11 a3 3 0 0 0 -3 3 v0" opacity="0.6"/></svg>),
  interp: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" {...p}><circle cx="12" cy="12" r="8"/><path d="M9.5 9.8 a2.5 2.5 0 1 1 3.2 3 c-0.8 0.4-0.7 1.2-0.7 1.7M12 17.3v.01" strokeLinecap="round"/></svg>),
  check: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...p}><path d="M5 12.5l4.5 4.5L19 7" strokeLinecap="round" strokeLinejoin="round"/></svg>),
  warn: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" {...p}><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5M12 16v.01" strokeLinecap="round"/></svg>),
  timeout: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" {...p}><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2M9 3h6" strokeLinecap="round"/></svg>),
  empty: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.3" {...p}><circle cx="12" cy="12" r="9" strokeDasharray="3 3"/><path d="M9 12h6" strokeLinecap="round"/></svg>),
  ingest: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" {...p}><path d="M12 3v10m0 0l-3.5-3.5M12 13l3.5-3.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" strokeLinecap="round"/></svg>),
  edit: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" {...p}><path d="M4 20h4L18.6 9.4a2 2 0 0 0-2.83-2.83L5 17.2 4 20Z" strokeLinejoin="round"/><path d="M14 7l3 3" strokeLinecap="round"/></svg>),
};

/* ---------------- Kind tag ---------------- */
function KindTag({ kind }) {
  const data = window.MYCELIUM_DATA;
  const def = data.statementKinds.find(k => k.name === kind);
  const layer = def ? def.layer : 'unknown';
  return (
    <span className={`kind layer-${layer}`} title={def ? `${kind} · ${layer} · ${def.gloss}` : kind}>
      <span className="kg" />{kind}
    </span>
  );
}

/* ---------------- Link tag ---------------- */
function LinkTag({ type, dir, hasWhen }) {
  return (
    <span className={`lt${hasWhen ? ' has-when' : ''}`} title={hasWhen ? `${type} · gated by a when-condition` : type}>
      {dir && <span className="lt-dir">{dir === 'out' ? '→' : '←'}</span>}
      {type}{hasWhen && ' ⟂'}
    </span>
  );
}

/* ---------------- Entity chip ---------------- */
function EntityChip({ entity }) {
  const router = useRouter();
  if (!entity) return null;
  return (
    <span className="echip" onClick={() => router.go({ view: 'entity', id: entity.id })} title={entity.description}>
      {entity.name}
    </span>
  );
}

/* ---------------- Score meter ---------------- */
function ScoreMeter({ score }) {
  const band = score >= 0.66 ? 'hi' : score >= 0.4 ? 'mid' : 'lo';
  return (
    <span className={`score ${band}`}>
      <span className="s-num">{score.toFixed(2)}</span>
      <span className="s-bar"><span className="s-fill" style={{ width: `${Math.max(4, score * 100)}%` }} /></span>
    </span>
  );
}

/* ---------------- Statement text with inline entity mentions ---------------- */
function StatementText({ statement, idx, className }) {
  const router = useRouter();
  const text = statement.text;
  const mentions = (statement.mentions || []).map(id => idx.byId[id]).filter(Boolean);

  // Build alias→entity map for the mentioned entities, longest-first.
  const aliasMap = [];
  mentions.forEach(e => {
    aliasMap.push({ surface: e.name, entity: e });
    (idx.namesByEntity[e.id] || []).forEach(n => aliasMap.push({ surface: n.text, entity: e }));
  });
  aliasMap.sort((a, b) => b.surface.length - a.surface.length);

  if (!aliasMap.length) return <p className={className}>{text}</p>;

  const pattern = aliasMap.map(a => escapeRe(a.surface)).join('|');
  const re = new RegExp(`\\b(${pattern})\\b`, 'gi');
  const out = [];
  let last = 0, m, used = new Set();
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const found = aliasMap.find(a => a.surface.toLowerCase() === m[0].toLowerCase());
    if (found && !used.has(found.entity.id)) {
      used.add(found.entity.id);
      out.push(
        <span key={m.index} className="mention" onClick={() => router.go({ view: 'entity', id: found.entity.id })}>
          {m[0]}
        </span>
      );
    } else {
      out.push(m[0]);
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <p className={className}>{out}</p>;
}

/* ---------------- Editable statement text ----------------
   Wraps statement display with an inline editor. On save, routes through
   Myc.editStatement — the substrate writes live (writer/admin) or auto-stages
   a draft (drafter); we report which happened. `statement` needs {id, text,
   kind}; mentions optional. `highlightQuery` (optional) renders the text with
   query highlighting instead of inline entity mentions (used in Find rows). */
function EditableStatementText({ statement, idx, className, onSaved, compact, highlightQuery }) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(statement.text);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [violations, setViolations] = useState(null);
  const [note, setNote] = useState(null);       // { kind:'saved'|'staged', draftId? }
  const [localText, setLocalText] = useState(null); // edited text to show after a live save

  const begin = (e) => { if (e) e.stopPropagation(); setVal(localText != null ? localText : statement.text); setEditing(true); setErr(null); setViolations(null); setNote(null); };
  const cancel = (e) => { if (e) e.stopPropagation(); setEditing(false); setErr(null); setViolations(null); };

  const doSave = (force) => {
    if (!val.trim() || busy) return;
    setBusy(true); setErr(null); setViolations(null);
    window.Myc.editStatement(statement.id, val.trim(), force)
      .then((res) => {
        if (res.status === 'rejected') { setViolations(res.violations); return null; }
        if (res.status === 'staged') {
          setEditing(false); setNote({ kind: 'staged', draftId: res.draftId });
          if (onSaved) onSaved(res);
          return null;
        }
        return window.Myc.refreshStatement(statement.id).then(() => {
          setLocalText(val.trim()); setEditing(false); setNote({ kind: 'saved' });
          if (onSaved) onSaved(res);
        });
      })
      .catch((e) => setErr((e.status === 401 || e.status === 403) ? 'You need write access to edit statements.' : (e.message || 'Save failed.')))
      .finally(() => setBusy(false));
  };

  if (editing) {
    return (
      <div className="stmt-edit" onClick={(e) => e.stopPropagation()}>
        <textarea className="stmt-edit-area" value={val} autoFocus spellCheck={false}
          rows={compact ? 3 : 4} onChange={(e) => setVal(e.target.value)} />
        {violations && (
          <div className="stmt-edit-warn">
            <I.warn width="15" height="15" />
            <div>
              <b>Phrasing check flagged this wording:</b>
              {violations.map((v, i) => <div key={i} className="sev-row">— {typeof v === 'string' ? v : (v.message || v.rule || JSON.stringify(v))}</div>)}
            </div>
          </div>
        )}
        {err && <div className="stmt-edit-err">{err}</div>}
        <div className="stmt-edit-actions">
          <button className="btn submit" disabled={busy || !val.trim()} onClick={(e) => { e.stopPropagation(); doSave(false); }}>
            <I.check width="14" height="14" />{busy ? 'Saving…' : 'Save'}
          </button>
          {violations && <button className="btn" disabled={busy} onClick={(e) => { e.stopPropagation(); doSave(true); }} title="Save despite the phrasing-catalog warnings">Save anyway</button>}
          <button className="btn ghost" disabled={busy} onClick={cancel}>Cancel</button>
        </div>
      </div>
    );
  }

  const text = localText != null ? localText : statement.text;
  const shown = localText != null ? { ...statement, text, title: window.Myc.titleOf(text) } : statement;
  return (
    <div className={`stmt-editable${compact ? ' compact' : ''}`}>
      {highlightQuery != null
        ? <p className={className}>{highlight(text, highlightQuery)}</p>
        : <StatementText statement={shown} idx={idx} className={className} />}
      <div className="stmt-editable-foot" onClick={(e) => e.stopPropagation()}>
        <button className="stmt-edit-btn" onClick={begin} title="Edit this statement's text"><I.edit width="13" height="13" />edit</button>
        {note && note.kind === 'saved' && <span className="stmt-edit-tag saved"><I.check width="12" height="12" />saved · re-embedded</span>}
        {note && note.kind === 'staged' && (
          <span className="stmt-edit-tag staged" onClick={() => router.go(note.draftId ? { view: 'draft', id: note.draftId } : { view: 'drafts' })}>
            <I.prov width="12" height="12" />staged in draft → review
          </span>
        )}
      </div>
    </div>
  );
}

/* ---------------- Empty state ---------------- */
function EmptyState({ title, blurb }) {
  return (
    <div className="empty">
      <I.empty className="e-glyph" />
      <div className="e-title">{title}</div>
      <div className="e-blurb">{blurb}</div>
    </div>
  );
}

Object.assign(window, {
  buildIndex, RouterCtx, useRouter, parseHash, routeToHash,
  highlight, escapeRe, I, KindTag, LinkTag, EntityChip, ScoreMeter, StatementText, EmptyState,
  EditableStatementText,
});
