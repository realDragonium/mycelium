// Shared components & helpers for Mycelium UI.

const { useState, useEffect, useMemo, useRef, useCallback, createContext, useContext } = React;

// ---------- Routing context ----------

const RouterCtx = createContext(null);
const useRouter = () => useContext(RouterCtx);

// ---------- Data lookups ----------

// Walk a when-clause tree and yield every leaf statement_id. Tolerates the
// legacy flat-string shape; otherwise leaves are {statement_id} and
// composites are {op, of: [...]}.
function* walkWhenLeaves(when) {
  if (!when) return;
  if (typeof when === 'string') { yield when; return; }
  if (when.statement_id) { yield when.statement_id; return; }
  if (when.op && Array.isArray(when.of)) {
    for (const child of when.of) yield* walkWhenLeaves(child);
  }
}

function buildIndex(data) {
  const byId = {};
  data.entities.forEach(e => byId[e.id] = { ...e, kind: 'entity' });
  // Preserve the statement's own kind (event/state/capability) as
  // `claimKind`. The byId-`kind` slot is the *record* kind, used by
  // routers, search and component-dispatch — overwriting it loses the
  // claim shape, so we save it under a different name.
  data.statements.forEach(b => byId[b.id] = { ...b, kind: 'statement', claimKind: b.kind });
  data.names.forEach(n => byId[n.id] = { ...n, kind: 'name' });

  const namesByEntity = {};
  data.names.forEach(n => {
    namesByEntity[n.entity] = namesByEntity[n.entity] || [];
    namesByEntity[n.entity].push(n);
  });

  const mentionsByEntity = {}; // entity id -> statement[]
  data.statements.forEach(b => {
    (b.mentions || []).forEach(eid => {
      mentionsByEntity[eid] = mentionsByEntity[eid] || [];
      mentionsByEntity[eid].push(b);
    });
  });

  const outgoing = {}; // bid -> [{to, type}]
  const incoming = {}; // bid -> [{from, type}]
  // Reverse index for statements used as a `when` condition. A statement
  // can be a leaf inside any number of links' when-trees; this map lets
  // the detail screen surface "this statement gates these edges" without
  // re-walking every link on render.
  const conditionUses = {}; // bid -> [link, ...]
  data.links.forEach(l => {
    outgoing[l.from] = outgoing[l.from] || [];
    outgoing[l.from].push(l);
    incoming[l.to] = incoming[l.to] || [];
    incoming[l.to].push(l);
    if (l.when) {
      const seen = new Set();
      for (const leafId of walkWhenLeaves(l.when)) {
        if (seen.has(leafId)) continue;
        seen.add(leafId);
        conditionUses[leafId] = conditionUses[leafId] || [];
        conditionUses[leafId].push(l);
      }
    }
  });

  // Entity↔entity adjacency. Same shape as statement-link adjacency
  // but keyed by entity_id and held in separate buckets so the entity
  // detail view can render them without overlap with statement-link
  // bookkeeping.
  const entityOutgoing = {}; // eid -> [{to, type}]
  const entityIncoming = {}; // eid -> [{from, type}]
  (data.entity_links || []).forEach(l => {
    entityOutgoing[l.from] = entityOutgoing[l.from] || [];
    entityOutgoing[l.from].push(l);
    entityIncoming[l.to] = entityIncoming[l.to] || [];
    entityIncoming[l.to].push(l);
  });

  return {
    byId, namesByEntity, mentionsByEntity,
    outgoing, incoming, conditionUses,
    entityOutgoing, entityIncoming,
  };
}

// ---------- Brand mark (mycelium hyphae) ----------

function BrandMark({ size = 22 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 22 22" fill="none">
      <circle cx="11" cy="11" r="2.2" fill="currentColor" />
      <circle cx="3.5" cy="6" r="1.4" fill="currentColor" />
      <circle cx="18.5" cy="5" r="1.2" fill="currentColor" />
      <circle cx="4" cy="17" r="1.2" fill="currentColor" />
      <circle cx="18" cy="16.5" r="1.6" fill="currentColor" />
      <circle cx="11" cy="2.5" r="1" fill="currentColor" />
      <circle cx="11" cy="19.5" r="1" fill="currentColor" />
      <g stroke="currentColor" strokeWidth="0.7" strokeLinecap="round" opacity="0.55">
        <path d="M11 11 L3.5 6" />
        <path d="M11 11 L18.5 5" />
        <path d="M11 11 L4 17" />
        <path d="M11 11 L18 16.5" />
        <path d="M11 11 L11 2.5" />
        <path d="M11 11 L11 19.5" />
      </g>
    </svg>
  );
}

function SearchIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="M10.5 10.5 L14 14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

// ---------- Search ----------

function highlight(text, query) {
  if (!query) return text;
  const q = query.trim();
  if (!q) return text;
  const re = new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig');
  const parts = text.split(re);
  return parts.map((p, i) =>
    re.test(p) ? <mark key={i}>{p}</mark> : <React.Fragment key={i}>{p}</React.Fragment>
  );
}

function searchAll(data, query) {
  const q = (query || '').trim().toLowerCase();
  if (!q) return [];
  const score = (text) => {
    const t = (text || '').toLowerCase();
    if (!t.includes(q)) return 0;
    if (t === q) return 100;
    if (t.startsWith(q)) return 60;
    if (new RegExp('\\b' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i').test(text || '')) return 40;
    return 20;
  };

  const results = [];
  data.entities.forEach(e => {
    const s = Math.max(score(e.name) + 5, score(e.description));
    if (s > 0) results.push({ kind: 'entity', record: e, score: s });
  });
  data.statements.forEach(b => {
    const s = Math.max(score(b.title), score(b.text));
    if (s > 0) results.push({ kind: 'statement', record: b, score: s });
  });
  data.names.forEach(n => {
    const s = score(n.text);
    if (s > 0) results.push({ kind: 'name', record: n, score: s });
  });
  results.sort((a, b) => b.score - a.score);
  return results;
}

// ---------- Top bar ----------

function TopBar({ small = false }) {
  const router = useRouter();
  const inputRef = useRef(null);
  const [val, setVal] = useState(router.query || '');

  useEffect(() => { setVal(router.query || ''); }, [router.query]);

  // Cmd-K / Ctrl-K focus
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <button className="brand" onClick={() => router.go({ view: 'landing' })} title="Mycelium home">
          <BrandMark />
          <span>Mycelium</span>
          <span className="brand-sub">read-only</span>
        </button>

        {small && (
          <form className="searchbar" onSubmit={(e) => { e.preventDefault(); router.go({ view: 'search', query: val }); }}>
            <SearchIcon />
            <input
              ref={inputRef}
              type="text"
              value={val}
              onChange={e => setVal(e.target.value)}
              placeholder="Search entities, statements, names…"
              spellCheck={false}
            />
            <span className="kbd">⌘K</span>
          </form>
        )}
        {!small && <div />}

        <nav className="topnav">
          <button className={router.view === 'graph' ? 'is-active' : ''} onClick={() => router.go({ view: 'graph' })}>Graph</button>
          <button className={router.view === 'entities' ? 'is-active' : ''} onClick={() => router.go({ view: 'entities' })}>Entities</button>
          <button className={router.view === 'browse' ? 'is-active' : ''} onClick={() => router.go({ view: 'browse' })}>Index</button>
          <button className={router.view === 'activity' ? 'is-active' : ''} onClick={() => router.go({ view: 'activity' })}>Activity</button>
          <button className={router.view === 'glossary' ? 'is-active' : ''} onClick={() => router.go({ view: 'glossary' })}>Glossary</button>
          <button className={router.view === 'gaps' ? 'is-active' : ''} onClick={() => router.go({ view: 'gaps' })}>Gaps</button>
          <button className={router.view === 'pending' ? 'is-active' : ''} onClick={() => router.go({ view: 'pending' })}>Pending</button>
          <button className={router.view === 'drafts' ? 'is-active' : ''} onClick={() => router.go({ view: 'drafts' })}>Drafts</button>
          <button onClick={() => { window.location.href = '/connect'; }}>Connect</button>
          <button className={router.view === 'settings' ? 'is-active' : ''} onClick={() => router.go({ view: 'settings' })}>Settings</button>
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}

function ThemeToggle() {
  const { tweaks, setTweak } = useContext(TweaksCtx);
  const next = tweaks.theme === 'dark' ? 'light' : 'dark';
  return (
    <button
      className="theme-toggle"
      onClick={() => setTweak('theme', next)}
      title={`Switch to ${next} theme`}
    >
      {tweaks.theme === 'dark' ? '◐ light' : '◑ dark'}
    </button>
  );
}

// Tweaks context — populated by app
const TweaksCtx = createContext({ tweaks: {}, setTweak: () => {} });

// Data context — bumps a version counter and re-fetches /api/data when
// the substrate is mutated through the UI. Consumers re-render off the
// `version` field; mutations call `refresh()` after a successful POST.
const DataCtx = createContext({ version: 0, refresh: async () => {} });
const useDataCtx = () => useContext(DataCtx);

// Minimal mutation helper — POST JSON, throw on non-2xx with the server's
// detail message so callers can surface it inline. Used by the entity-link
// editor and any future write affordance.
async function postJSON(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = `${r.status}`;
    try { const j = await r.json(); if (j?.detail) detail = j.detail; } catch (_) {}
    throw new Error(detail);
  }
  return r.json();
}

// ---------- Kind tag ----------

function KindTag({ kind }) {
  return (
    <span className={`kind k-${kind}`}>
      <span className="dot" />
      {kind}
    </span>
  );
}

// Tag for the per-statement claim kind (event / state / capability,
// open-vocabulary). Distinct from KindTag, which tags the *record*
// kind (statement / entity / name).
function ClaimKindTag({ kind }) {
  if (!kind) return null;
  return <span className={`claim-kind ck-${kind}`}>{kind}</span>;
}

// ---------- Mention chips ----------

function EntityChip({ entity, asName = false, name = null }) {
  const router = useRouter();
  return (
    <button
      className={`chip${asName ? ' k-name' : ''}`}
      onClick={() => router.go({ view: 'entity', id: entity.id })}
      title={asName ? `Alias for ${entity.name}` : entity.name}
    >
      {asName ? name.text : entity.name}
    </button>
  );
}

// ---------- Statement text with linkified entity mentions ----------

function StatementText({ statement, byId, className = 'statement-text' }) {
  const mentioned = (statement.mentions || []).map(id => byId[id]).filter(Boolean);
  if (!mentioned.length) return <p className={className} style={{marginTop:8}}>{statement.text}</p>;

  // Sort by length desc to avoid sub-matching
  const targets = mentioned.slice().sort((a, b) => b.name.length - a.name.length);
  let text = statement.text;
  // Build segments via repeated split
  let segments = [{ t: text, e: null }];
  targets.forEach(ent => {
    const re = new RegExp('\\b(' + ent.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')\\b', 'i');
    const next = [];
    segments.forEach(seg => {
      if (seg.e) { next.push(seg); return; }
      let rest = seg.t;
      while (true) {
        const m = rest.match(re);
        if (!m) { if (rest) next.push({ t: rest, e: null }); break; }
        if (m.index > 0) next.push({ t: rest.slice(0, m.index), e: null });
        next.push({ t: m[0], e: ent });
        rest = rest.slice(m.index + m[0].length);
      }
    });
    segments = next;
  });

  const router = useRouter();
  return (
    <p className={className} style={{marginTop:8}}>
      {segments.map((s, i) => s.e
        ? <span key={i} className="ent-mention" onClick={() => router.go({ view: 'entity', id: s.e.id })}>{s.t}</span>
        : <React.Fragment key={i}>{s.t}</React.Fragment>
      )}
    </p>
  );
}

function StatementQuote({ statement, byId }) {
  return <StatementText statement={statement} byId={byId} className="bv-quote" />;
}

// ---------- Footer ----------

function Footer() {
  const data = window.MYCELIUM_DATA;
  return (
    <footer className="footer">
      <div className="ftr-inner">
        <span>mycelium · v0.1 · read-only</span>
        <span>
          {data.entities.length}e · {data.statements.length}b · {data.names.length}n · {data.links.length}l
        </span>
      </div>
    </footer>
  );
}

// ---------- Edit-affordance hint ----------
function EditHint({ children }) {
  const { tweaks } = useContext(TweaksCtx);
  if (!tweaks.showEditAffordances) return null;
  return <span className="edit-hint">{children || 'edit later'}</span>;
}

Object.assign(window, {
  RouterCtx, useRouter,
  TweaksCtx,
  DataCtx, useDataCtx, postJSON,
  buildIndex,
  BrandMark, SearchIcon,
  searchAll, highlight,
  TopBar, ThemeToggle,
  KindTag, ClaimKindTag, EntityChip, StatementText, StatementQuote,
  Footer, EditHint,
});
