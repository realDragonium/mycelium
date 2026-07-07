// mentions.jsx — the derived-mention review queue.
//
// Mentions (statement → entity) are derived from statement text automatically.
// A match on a short or common entity name is too ambiguous to auto-link, so
// it is held here for a human to judge ONE occurrence at a time: approve
// materializes the real mention; reject writes nothing. The same word can be a
// real reference in one statement and noise in another, so review is per
// (statement, name) occurrence — there is deliberately no bulk action.
//
// Backed by two HTTP-only endpoints via Myc.pendingMentions / Myc.actOnMention.
const { useState: useStateM, useEffect: useEffectM } = React;

/* --------------------------- shared cached store --------------------------- */
// One cached fetch of every pending row (status=all), held on a window var so
// the queue screen and the topbar badge share state and re-render together.
// Mirrors the drafts store pattern.
const pmSubs = new Set();
let pmInFlight = null;
function pmNotify() { pmSubs.forEach((f) => f()); }

function refreshPending() {
  pmInFlight = window.Myc.pendingMentions('all', 1000, 0)
    .then((rows) => { window.__MYC_PENDING = rows; window.__MYC_PENDING_ERR = null; pmNotify(); return rows; })
    .catch((e) => { window.__MYC_PENDING_ERR = e; pmNotify(); })
    .finally(() => { pmInFlight = null; });
  return pmInFlight;
}

function useMycPending() {
  const [, set] = useStateM(0);
  useEffectM(() => {
    const f = () => set((n) => n + 1);
    pmSubs.add(f);
    if (!window.__MYC_PENDING && !pmInFlight) refreshPending();
    return () => pmSubs.delete(f);
  }, []);
  return window.__MYC_PENDING; // undefined until the first fetch resolves
}

/* ------------------------------- bits ------------------------------- */
// Highlight the suspect name where it appears in the statement, in context.
function pmHighlightName(text, name) {
  const i = String(text).toLowerCase().indexOf(String(name || '').toLowerCase());
  if (i < 0 || !name) return text;
  return (
    <>
      {text.slice(0, i)}
      <mark>{text.slice(i, i + name.length)}</mark>
      {text.slice(i + name.length)}
    </>
  );
}

const PM_TONE = { open: 'open', approved: 'submitted', rejected: 'rejected' };
function PendingBadge({ status }) {
  return <span className={`st-badge ${PM_TONE[status] || 'open'}`}>{status}</span>;
}

function MentionRow({ row, onAction, busy }) {
  const router = useRouter();
  const idx = window.MYCELIUM_INDEX;
  const entity = idx.byId[row.entity_id];
  const open = row.status === 'open';
  const when = (row.created_at || '').slice(0, 16).replace('T', ' ');
  return (
    <div className={`op${open ? '' : ' resolved'}`} style={open ? null : { opacity: 0.62 }}>
      <div className="op-head">
        <KindTag kind={row.statement_kind} />
        <span className="op-seq" style={{ cursor: 'pointer' }} title="open the statement"
          onClick={() => router.go({ view: 'statement', id: row.statement_id })}>{row.statement_id}</span>
        <span className="op-spacer" />
        <PendingBadge status={row.status} />
        {open && (
          <div className="draft-actions" style={{ marginLeft: 10 }}>
            <button className="btn submit" disabled={busy} title="This text really refers to the entity — create the mention."
              onClick={() => onAction(row.id, 'approve')}><I.check width="14" height="14" />Approve</button>
            <button className="btn ghost-danger" disabled={busy} title="Noise, not a reference to the entity — write no mention."
              onClick={() => onAction(row.id, 'reject')}>Reject</button>
          </div>
        )}
      </div>
      <div className="op-body">
        <EditableStatementText
          statement={{ id: row.statement_id, text: row.statement_text, kind: row.statement_kind, mentions: [] }}
          idx={idx} className="op-stmt-text" highlightQuery={row.name}
          onSaved={() => refreshPending()} compact />
        <div className="op-name-line" style={{ marginTop: 10 }}>
          <span className="alias-q">“{row.name}”</span>
          <span className="arr">⋯ mentions ⋯→</span>
          {entity
            ? <EntityChip entity={entity} />
            : <span className="echip" style={{ cursor: 'default' }} title={row.entity_id}>{row.entity_id}</span>}
          <span style={{ flex: 1 }} />
          <span style={{ fontFamily: 'var(--mono)', fontSize: 'var(--fs-2xs)', color: 'var(--ink-4)' }}>found {when}</span>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------- screen ------------------------------- */
function MentionsScreen() {
  const router = useRouter();
  const all = useMycPending();
  const err = window.__MYC_PENDING_ERR;
  const [filter, setFilter] = useStateM('open');
  const [busyId, setBusyId] = useStateM(null);
  const [actErr, setActErr] = useStateM(null);

  const onAction = (id, action) => {
    setBusyId(id); setActErr(null);
    window.Myc.actOnMention(id, action)
      .then(() => refreshPending())
      .catch((e) => setActErr((e && e.message) || 'Action failed.'))
      .finally(() => setBusyId(null));
  };

  // Not loaded yet.
  if (all === undefined || all === null) {
    if (err) {
      const unauth = err.status === 401 || err.status === 403;
      return (
        <main className="page narrow">
          <EmptyState title={unauth ? 'Sign in to review mentions' : 'Could not load pending mentions'}
            blurb={unauth ? 'This review queue requires an authenticated session.' : String(err.message || err)} />
        </main>
      );
    }
    return <main className="page narrow"><div className="rail-empty" style={{ padding: '40px 2px', fontFamily: 'var(--mono)', fontSize: 'var(--fs-xs)', color: 'var(--ink-4)' }}>// loading the review queue…</div></main>;
  }

  const counts = { all: all.length, open: 0, approved: 0, rejected: 0 };
  all.forEach((r) => { counts[r.status] = (counts[r.status] || 0) + 1; });
  const shown = filter === 'all' ? all : all.filter((r) => r.status === filter);

  return (
    <main className="page narrow">
      <div className="crumbs"><a onClick={() => router.go({ view: 'landing' })}>~</a><span className="sep">/</span><span className="here">mentions</span></div>

      <div className="drafts-head">
        <h1>Pending mentions</h1>
        <span className="dh-sub">derived · per-occurrence review</span>
      </div>
      <p className="ingest-sub" style={{ marginTop: -4 }}>
        A statement's text matched a short or ambiguous entity name — too uncertain to link on its own. <b>Approve</b> to
        record the mention, or <b>reject</b> if the word here doesn't really refer to that entity. Each occurrence is
        judged on its own; nothing is bulk-applied.
      </p>

      <div className="drafts-summary">
        <div className="ds-cell"><div className="ds-n write">{counts.open}</div><div className="ds-l">open · awaiting review</div></div>
        <div className="ds-cell"><div className="ds-n">{counts.approved}</div><div className="ds-l">approved · materialized</div></div>
        <div className="ds-cell"><div className="ds-n">{counts.rejected}</div><div className="ds-l">rejected · written off</div></div>
      </div>

      {actErr && <div className="draft-banner" style={{ borderColor: 'var(--bad, #e0533d)' }}><span className="dbi"><I.warn width="15" height="15" /></span><span>{actErr}</span></div>}

      <div className="draft-filters">
        <span className="dfl">show</span>
        {['open', 'approved', 'rejected', 'all'].map((f) => (
          <button key={f} className={`fchip${filter === f ? ' on' : ''}`} onClick={() => setFilter(f)}>{f}<span className="fc-ct">{counts[f] || 0}</span></button>
        ))}
      </div>

      {shown.length === 0 ? (
        <div style={{ marginTop: 24 }}>
          <EmptyState
            title={filter === 'open' ? 'Nothing to review' : `No ${filter} occurrences`}
            blurb={filter === 'open' ? 'Every suspect match has been decided. New ones appear here as statements are ingested.' : 'Switch the filter to see other occurrences.'} />
        </div>
      ) : (
        <div className="ops" style={{ marginTop: 16 }}>
          {shown.map((r) => <MentionRow key={r.id} row={r} onAction={onAction} busy={busyId === r.id} />)}
        </div>
      )}
    </main>
  );
}

Object.assign(window, { MentionsScreen, useMycPending, refreshPending });
