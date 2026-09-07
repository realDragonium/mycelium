// drafts.jsx — the draft/curator spine (§3): the live draft REST surface via Myc.drafts.
// list → summaries, get_draft → reviewable diff, discard_draft_op / submit_draft / withdraw_draft.
// Shared DraftReview diff (used by ingest's draft handoff + the drafts list).
const { useState: useStateD, useEffect: useEffectD, useMemo: useMemoD, useRef: useRefD } = React;

/* ============================ live store ============================ */
// One cached fetch of Myc.drafts.list('all'), held on a window var so every
// surface (app badge, DraftsList) shares it. A subscriber set re-renders the
// mounted components after a refresh. No localStorage, no seed — this is the
// real draft spine.
const draftSubs = new Set();
function notifyDrafts() { draftSubs.forEach(f => f()); }

// raw serialize_draft (+ op_count) → the summary shape the cockpit reads.
function toSummary(d) {
  return {
    id: d.id,
    title: d.title || Myc.titleOf(''),
    status: d.status,
    review_assessment: d.review_assessment || null,
    createdAt: Date.parse(d.created_at),
    origin: d.created_by || 'ingest',
    opCount: d.op_count || 0,
  };
}

let draftsInFlight = null;
function refreshDrafts() {
  draftsInFlight = Myc.drafts.list('all')
    .then(res => {
      window.__MYC_DRAFTS = ((res && res.drafts) || []).map(toSummary);
      window.__MYC_DRAFTS_ERR = null;
      return window.__MYC_DRAFTS;
    })
    .catch(err => {
      window.__MYC_DRAFTS_ERR = err;
      // keep any prior cache rather than blanking the UI on a transient error.
      if (!window.__MYC_DRAFTS) window.__MYC_DRAFTS = [];
      return window.__MYC_DRAFTS;
    })
    .finally(() => { draftsInFlight = null; notifyDrafts(); });
  return draftsInFlight;
}

// Hook: subscribes to the store, kicks off the one-time fetch on first use,
// and returns the cached summary array. The array + `.status` contract is what
// app.jsx (open-draft badge) and DraftsList depend on.
function useMycDrafts() {
  const [, bump] = useStateD(0);
  useEffectD(() => {
    const f = () => bump(n => n + 1);
    draftSubs.add(f);
    if (!window.__MYC_DRAFTS && !draftsInFlight) refreshDrafts();
    return () => draftSubs.delete(f);
  }, []);
  return window.__MYC_DRAFTS || [];
}

function relTime(ts) {
  if (!ts || isNaN(ts)) return '';
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

/* ============================ op shape adaptation ============================ */
// Resolve a statement/entity id to its human handle via the live index.
function titleFor(id) {
  if (!id) return '';
  const rec = (window.MYCELIUM_INDEX && window.MYCELIUM_INDEX.byId[id]) || null;
  if (!rec) return String(id);
  return rec.title || rec.text || rec.name || String(id);
}

// Real op `kind` → review category. The list endpoint only gives op_count, so
// per-category breakdown is only available inside DraftReview (which has ops).
function categoryOf(op) {
  const k = op.type;
  if (k === 'flag') return 'flagged'; // a record for the curator, not a queued write
  if (k === 'upsert_statement' || k === 'upsert_statements' || k === 'patch_statement' || k === 'replace_text' || k === 'merge_statements') return 'statements';
  if (k === 'upsert_entity') return 'entities';
  if (k === 'upsert_name' || k === 'alias_suggestion') return 'names';
  return 'links'; // add_links | add_entity_links
}

// A `flag` op is an unresolved fragment `ingest_text` refused to guess a
// statement out of; it never replays, so it stays here until someone resolves
// it and discards it. Everything else carries no flag reason.
function flagReason(op) {
  if (op.kind !== 'flag') return false;
  const p = op.payload || {};
  return p.detail ? `${p.reason} — ${p.detail}` : (p.reason || 'unresolved fragment');
}

/* ============================ op renderers ============================ */
// Compact mono key/value for raw payloads we don't render structurally.
function KV({ obj }) {
  const entries = Object.entries(obj || {});
  if (!entries.length) return null;
  return (
    <div className="op-kv" style={{ fontFamily: 'var(--mono)', fontSize: 'var(--fs-xs)', color: 'var(--ink-4)', display: 'flex', flexWrap: 'wrap', gap: '4px 14px', marginTop: 4 }}>
      {entries.map(([k, v]) => (
        <span key={k}><span style={{ color: 'var(--ink-5)' }}>{k}</span> {typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
      ))}
    </div>
  );
}

function ResolvedRef({ id }) {
  const router = useRouter();
  const rec = (window.MYCELIUM_INDEX && window.MYCELIUM_INDEX.byId[id]) || null;
  const label = titleFor(id);
  const view = rec && rec._kind === 'entity' ? 'entity' : rec && rec._kind === 'statement' ? 'statement' : null;
  return <span className="lp" title={label} style={{ cursor: view ? 'pointer' : 'default' }} onClick={() => view && router.go({ view, id })}>{label}</span>;
}

function OpBody({ op }) {
  const p = op.payload || {};

  if (op.type === 'alias_suggestion') return <div><p>Alias “{p.proposal?.alias}” → <ResolvedRef id={p.proposal?.entity_id} /></p><p>{p.status === 'pending' ? 'Needs human review' : p.status}. <a href="#/names">Review in Names &amp; aliases</a></p><blockquote>{p.evidence?.quote}</blockquote><p>{p.proposal?.reason}</p></div>;

  if (op.type === 'upsert_statement') {
    return (<><div style={{ marginBottom: 8 }}><KindTag kind={p.kind} /></div><div className="op-stmt-text">{p.text}</div></>);
  }

  if (op.type === 'upsert_statements') {
    const stmts = p.statements || [];
    return (
      <>
        <div className="op-stmt-text" style={{ color: 'var(--ink-4)', fontFamily: 'var(--mono)', fontSize: 'var(--fs-xs)' }}>{stmts.length} statement{stmts.length === 1 ? '' : 's'}</div>
        {stmts.map((s, i) => (
          <div key={i} className="op-stmt-text" style={{ marginTop: 6, display: 'flex', gap: 8, alignItems: 'baseline' }}>
            {s.kind && <KindTag kind={s.kind} />}<span>{s.text}</span>
          </div>
        ))}
      </>
    );
  }

  if (op.type === 'upsert_entity') {
    return (<><div className="op-ent-name">{p.name}</div><div className="op-ent-desc">{p.description}</div></>);
  }

  if (op.type === 'upsert_name') {
    return (
      <div className="op-name-line">
        <span className="alias-q">“{p.text}”</span><span className="arr">→</span>
        <ResolvedRef id={p.entity_id} />
      </div>
    );
  }

  if (op.type === 'add_links') {
    const links = p.links || [];
    return (
      <>{links.map((l, i) => (
        <div key={i} className="op-link-line">
          <ResolvedRef id={l.from_id} />
          <LinkTag type={l.link_type} hasWhen={!!l.when} />
          <ResolvedRef id={l.to_id} />
          {l.when && <span className="when-chip">⟂ when</span>}
        </div>
      ))}</>
    );
  }

  if (op.type === 'add_entity_links') {
    const links = p.links || [];
    return (
      <>{links.map((l, i) => (
        <div key={i} className="op-link-line">
          <ResolvedRef id={l.from_entity_id} />
          <LinkTag type={l.link_type} />
          <ResolvedRef id={l.to_entity_id} />
        </div>
      ))}</>
    );
  }

  if (op.type === 'patch_statement') {
    const { id, ...rest } = p;
    return (
      <>
        <div className="op-name-line"><span className="arr">patch</span><ResolvedRef id={id} /></div>
        <KV obj={rest} />
      </>
    );
  }

  if (op.type === 'flag') {
    return <div className="op-stmt-text">{p.text}</div>;
  }

  if (op.type === 'merge_statements') {
    return (
      <div className="op-link-line">
        <ResolvedRef id={p.from_id} />
        <span className="arr">⤳ merge into</span>
        <ResolvedRef id={p.into_id} />
      </div>
    );
  }

  // replace_text / unknown → honest fallback: the op type + compact payload.
  return (
    <>
      <div className="op-stmt-text" style={{ color: 'var(--ink-4)', fontFamily: 'var(--mono)', fontSize: 'var(--fs-xs)' }}>{op.type}</div>
      <KV obj={p} />
    </>
  );
}

function OpCard({ op, onDiscard, onHover, active, readOnly }) {
  return (
    <div className={`op${op.flagged ? ' flagged' : ''}${active ? ' active' : ''}`} onMouseEnter={() => onHover(op.quote)} onMouseLeave={() => onHover(null)}>
      <div className="op-head">
        <span className="op-plus">+</span>
        <span className="op-type">{op.type}</span>
        <span className="op-seq">op {String(op.seq).padStart(2, '0')}</span>
        <span className="op-spacer" />
        {op.flagged && <span className="op-flag-tag"><I.warn width="12" height="12" />needs review</span>}
        {!readOnly && <button className="op-discard" title="Discard this op" onClick={() => onDiscard(op.seq)}>✕</button>}
      </div>
      <div className="op-body">
        <OpBody op={op} />
        {op.flagged && <div className="op-flag-reason"><I.warn className="ofr-i" width="15" height="15" /><span>{op.flagged}</span></div>}
      </div>
    </div>
  );
}

// Real drafts persist no source text and ops carry no quote, so this always
// renders the honest "no stored source" branch. Kept for layout; the
// hover-to-highlight is inert because there is nothing to highlight.
function SourceRail({ source, sourceType, activeQuote }) {
  let body;
  if (!source) body = <span style={{ color: 'var(--ink-5)' }}>// no source — these ops were authored or extracted server-side; the raw text is not stored on the draft.</span>;
  else if (activeQuote && source.includes(activeQuote)) {
    const i = source.indexOf(activeQuote);
    body = (<>{source.slice(0, i)}<span className="src-hit">{activeQuote}</span>{source.slice(i + activeQuote.length)}</>);
  } else body = source;
  return (
    <aside className="src-rail">
      <div className="src-rail-head"><span className="srt">source text</span>{sourceType && <span className="src-type-tag">{sourceType}</span>}</div>
      <div className="src-text">{body}</div>
      <div className="src-rail-foot">// real drafts store no source text — nothing is written until you submit for review.</div>
    </aside>
  );
}

/* ============================ DraftReview (get_draft diff) ============================ */
// raw serialize_draft (with ops) → the review shape this component renders.
function adaptDraft(raw) {
  const d = raw || {};
  return {
    id: d.id,
    title: d.title,
    status: d.status,
    review_assessment: d.review_assessment || null,
    createdAt: Date.parse(d.created_at),
    submittedAt: Date.parse(d.submitted_at),
    source: null,
    sourceType: '',
    ops: (d.ops || []).map(o => ({ seq: o.seq, type: o.kind, payload: o.payload, flagged: flagReason(o), quote: null })),
  };
}

function DraftAssessment({ assessment, compact = false }) {
  if (!assessment) return null;
  const labels = {
    good: 'Good',
    changes_suggested: 'Changes suggested',
    reject: 'Reject suggested',
    needs_context: 'Needs context',
  };
  const result = assessment.status === 'running' ? 'Running'
    : assessment.status === 'failed' ? 'Failed'
    : labels[assessment.label] || 'Completed';
  const badge = <span style={{ fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 600 }}>
    AI review: {result}{assessment.stale ? ' · Stale' : ''}
  </span>;
  if (compact) return <div style={{ marginTop: 6, color: 'var(--ink-3)' }}>{badge}</div>;

  return (
    <section aria-label="AI review" style={{ padding: 14, marginBottom: 18, border: '1px solid var(--line)', borderRadius: 6, color: 'var(--ink-3)', fontSize: 12, lineHeight: 1.5, overflowWrap: 'anywhere' }}>
      {badge}
      <div style={{ marginTop: 4 }}>Reviewer: {draftReviewProviderName(assessment.provider)} · {assessment.model || 'Model not recorded'} · Effort: {assessment.reasoning_effort ?? 'Model default'}</div>
      <div style={{ marginTop: 4 }}>
        {assessment.mode === 'review-only' ? 'Review only. This review does not edit, reject, or apply the draft.' : 'Review and apply.'}
        {' '}Status: {assessment.status}.{' '}
        {assessment.application === 'applied' ? 'Draft applied by this review.'
          : assessment.application === 'rejected' ? 'Draft rejected by this review.'
          : 'No automatic application or rejection.'}
      </div>
      {assessment.stale && <p>This assessment is stale: it reviewed revision {assessment.draft_revision}, and the draft has changed.</p>}
      {assessment.rationale && <p style={{ whiteSpace: 'pre-wrap' }}>{assessment.rationale}</p>}
      {assessment.detail && <p style={{ whiteSpace: 'pre-wrap' }}>{assessment.detail}</p>}
      {assessment.questions.length > 0 && <div>
        <strong>Questions</strong>
        <ul style={{ margin: '6px 0', paddingLeft: 20 }}>{assessment.questions.map((question, i) => <li key={i}>{question}</li>)}</ul>
      </div>}
      {assessment.corrections.length > 0 && <div>
        <strong>Suggested corrections</strong>
        <ul style={{ margin: '6px 0', paddingLeft: 20 }}>{assessment.corrections.map((correction, i) => (
          <li key={i} style={{ marginTop: 6 }}>
            <strong>{correction.action}</strong>{correction.operation_ref ? ` ${correction.operation_ref}` : ''}{correction.tool_name ? ` · ${correction.tool_name}` : ''}: {correction.reason}
            {correction.payload_json && <details><summary>Proposed payload</summary><pre style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>{correction.payload_json}</pre></details>}
          </li>
        ))}</ul>
      </div>}
    </section>
  );
}


function DraftReview({ id }) {
  const router = useRouter();
  const [state, setState] = useStateD({ loading: true, draft: null, error: null });
  const [filter, setFilter] = useStateD('all');
  const [activeQuote, setActiveQuote] = useStateD(null);
  const [busy, setBusy] = useStateD(false);
  const [reviewSettings, setReviewSettings] = useStateD(null);

  useEffectD(() => {
    let cancelled = false;
    const loadSettings = () => Myc.drafts.reviewSettings().then(settings => {
      if (!cancelled) setReviewSettings(settings);
    }).catch(error => {
      if (!cancelled) { setReviewSettings(null); setState(s => ({ ...s, error })); }
    });
    loadSettings();
    window.addEventListener('focus', loadSettings);
    window.addEventListener('draft-review-settings-changed', loadSettings);
    return () => { cancelled = true; window.removeEventListener('focus', loadSettings); window.removeEventListener('draft-review-settings-changed', loadSettings); };
  }, [id]);

  const load = () => {
    setState(s => ({ ...s, loading: true, error: null }));
    return Myc.drafts.get(id)
      .then(res => setState({ loading: false, draft: adaptDraft(res && res.draft), error: null }))
      .catch(err => setState({ loading: false, draft: null, error: err }));
  };
  useEffectD(() => { load(); }, [id]);
  useEffectD(() => {
    if (state.draft?.review_assessment?.status !== 'running' || busy) return;
    let cancelled = false;
    let timer;
    const poll = async () => {
      try {
        const res = await Myc.drafts.get(id);
        if (cancelled) return;
        setState({ loading: false, draft: adaptDraft(res && res.draft), error: null });
        refreshDrafts();
      } catch (error) {
        if (!cancelled) {
          setState(s => ({ ...s, error }));
          timer = setTimeout(poll, 3000);
        }
      }
    };
    timer = setTimeout(poll, 3000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [id, state.draft, busy]);

  if (state.loading) {
    return <main className="page narrow"><div className="rail-empty" style={{ padding: '48px 2px', fontFamily: 'var(--mono)', fontSize: 'var(--fs-xs)', color: 'var(--ink-4)' }}>// loading draft {id}…</div></main>;
  }
  if (state.error && !state.draft) {
    const e = state.error;
    const unauth = e.status === 401 || e.status === 403;
    return <main className="page narrow"><EmptyState title={unauth ? 'Sign in to view this draft' : 'Could not load draft'} blurb={unauth ? 'Your session lacks the role needed to read drafts.' : (e.message || 'The draft request failed.')} /></main>;
  }
  const draft = state.draft;
  if (!draft || !draft.id) {
    return <main className="page narrow"><EmptyState title="Draft not found" blurb="It may have been submitted, withdrawn, or never existed. Check your drafts." /></main>;
  }

  const ops = draft.ops;
  const readOnly = draft.status !== 'open';
  const hasAliases = ops.some(op => op.type === 'alias_suggestion');
  const pendingAliases = ops.some(op => op.type === 'alias_suggestion' && op.payload?.status === 'pending');
  const counts = { all: ops.length, statements: 0, entities: 0, names: 0, links: 0, flagged: 0 };
  ops.forEach(o => { const c = categoryOf(o); if (c !== 'flagged') counts[c]++; if (o.flagged) counts.flagged++; });
  const shown = ops.filter(o => filter === 'all' ? true : filter === 'flagged' ? o.flagged : categoryOf(o) === filter);

  const runReview = async () => {
    setBusy(true);
    setState(s => ({ ...s, error: null }));
    try {
      const settings = await Myc.drafts.reviewSettings();
      setReviewSettings(settings);
      if (settings.mode === 'off' || !settings.can_review) return;
      await Myc.drafts.review(id);
      await load();
      await refreshDrafts();
    } catch (error) {
      setState(s => ({ ...s, error }));
    } finally {
      setBusy(false);
    }
  };

  const onDiscardOp = (seq) => {
    setBusy(true);
    Myc.drafts.discardOp(id, seq).then(load).then(() => refreshDrafts()).finally(() => setBusy(false));
  };
  const onSubmit = () => {
    setBusy(true);
    Myc.drafts.submit(id).then(() => refreshDrafts()).then(() => router.go({ view: 'drafts' })).catch(() => setBusy(false));
  };
  const onWithdraw = () => {
    setBusy(true);
    Myc.drafts.withdraw(id).then(() => refreshDrafts()).then(() => router.go({ view: 'drafts' })).catch(() => setBusy(false));
  };

  return (
    <main className="page">
      <div className="crumbs">
        <a onClick={() => router.go({ view: 'landing' })}>~</a><span className="sep">/</span>
        <a onClick={() => router.go({ view: 'drafts' })}>drafts</a><span className="sep">/</span><span className="here">{draft.id}</span>
      </div>
      <div className="draft-head">
        <span className="dh-badge"><I.prov width="13" height="13" />draft · diff</span>
        <span className="dh-id">{draft.id}</span>
        <span className="dh-title">{draft.title}</span>
        {counts.flagged > 0 && <span className="dh-flag"><I.warn width="13" height="13" />{counts.flagged} flagged</span>}
        <span className="dh-spacer" />
        {!readOnly && (
          <div className="draft-actions">
            <button className="btn ghost-danger" disabled={busy || pendingAliases} onClick={onWithdraw}>Discard draft</button>
            <button className="btn submit" disabled={busy || ops.length === 0} onClick={onSubmit}><I.check width="15" height="15" />Submit for review</button>
          </div>
        )}
      </div>

      {draft.status === 'submitted' && <div className="draft-banner"><span className="dbi"><I.check width="15" height="15" /></span><span><b>Submitted {relTime(draft.submittedAt)}.</b> {hasAliases ? 'Alias decisions are recorded individually; remaining operations are queued for review.' : `These ${ops.length} ops are queued for review. Nothing has landed in the substrate yet.`}</span></div>}
      {draft.status === 'approved' && <div className="draft-banner">Approved. The draft has been applied to the substrate.</div>}
      {(draft.status === 'rejected' || draft.status === 'withdrawn') && <div className="draft-banner">{draft.status === 'rejected' ? 'Rejected' : 'Withdrawn'}. {hasAliases ? 'The draft is closed. Earlier accepted aliases remain recorded in Names & aliases.' : 'The draft is closed without applying its operations.'}</div>}
      {pendingAliases && <p>Review each alias suggestion in <a href="#/names">Names &amp; aliases</a> before applying or closing this draft. Automatic review stays advisory.</p>}
      {state.error && <p role="alert" style={{ color: 'var(--red, #dc2626)', fontSize: 13 }}>{state.error.message || 'The draft request failed.'}</p>}
      {draft.status === 'submitted' && (
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 18 }}>
          <button onClick={runReview} disabled={busy || draft.review_assessment?.status === 'running' || !reviewSettings?.can_review || reviewSettings.mode === 'off'}
                  className="btn submit">
            {draft.review_assessment?.status === 'running' ? 'Review running…' : draft.review_assessment ? 'Run again' : 'Run review'}
          </button>
          <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>
            {!reviewSettings ? 'Review settings unavailable.'
              : !reviewSettings.can_review ? 'A real curator role is required to run reviews.'
              : reviewSettings.mode === 'off' ? 'Review is off. An administrator can enable it in draft review settings.'
              : reviewSettings.mode === 'review-only' ? 'Current mode: Review only.' : 'Current mode: Review and apply.'}
            {reviewSettings?.can_review && reviewSettings.mode !== 'off' && reviewSettings.provider && ` ${draftReviewProviderName(reviewSettings.provider)} · ${reviewSettings.model || 'No model configured'}.`}
          </span>
        </div>
      )}

      <p style={{ marginBottom: 20, fontSize: 13 }}><a href="#/settings">AI settings</a></p>
      <DraftAssessment assessment={draft.review_assessment} />

      <div className="draft-grid">
        <div>
          <div className="draft-filters">
            <span className="dfl">show</span>
            {['all', 'statements', 'entities', 'names', 'links', 'flagged'].map(f => (
              <button key={f} className={`fchip${filter === f ? ' on' : ''}${f === 'flagged' ? ' flag' : ''}`} onClick={() => setFilter(f)}>{f}<span className="fc-ct">{counts[f] || 0}</span></button>
            ))}
          </div>
          {ops.length === 0 ? <EmptyState title="Draft is empty" blurb="Every op was discarded." />
            : shown.length === 0 ? <div className="rail-empty" style={{ padding: '24px 2px', fontFamily: 'var(--mono)', fontSize: 'var(--fs-xs)', color: 'var(--ink-4)' }}>// no ops match this filter</div>
            : <div className="ops">{shown.map(op => <OpCard key={op.seq} op={op} active={activeQuote === op.quote} onHover={setActiveQuote} onDiscard={onDiscardOp} readOnly={readOnly || op.type === 'alias_suggestion'} />)}</div>}
        </div>
        <SourceRail source={draft.source} sourceType={draft.sourceType} activeQuote={activeQuote} />
      </div>
    </main>
  );
}

/* ============================ DraftsList (list drafts) ============================ */
function DraftsList() {
  const router = useRouter();
  const drafts = useMycDrafts();
  const [filter, setFilter] = useStateD(/** @type {'active' | 'completed' | 'all'} */ ('active'));
  useEffectD(() => {
    if (!draftsInFlight) refreshDrafts();
  }, []);
  useEffectD(() => {
    if (!drafts.some(d => d.review_assessment?.status === 'running')) return;
    let cancelled = false;
    let timer;
    const poll = async () => {
      await refreshDrafts();
      if (!cancelled) timer = setTimeout(poll, 3000);
    };
    timer = setTimeout(poll, 3000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [drafts]);
  const sorted = [...drafts].sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));
  const open = sorted.filter(d => d.status === 'open');
  const submitted = sorted.filter(d => d.status === 'submitted');
  const pendingOps = open.reduce((n, d) => n + (d.opCount || 0), 0);
  const activeCount = open.length + submitted.length;
  const shown = sorted.filter(d => {
    const active = d.status === 'open' || d.status === 'submitted';
    return filter === 'all' || (filter === 'active' ? active : !active);
  });
  /** @type {ReadonlyArray<{id: 'active' | 'completed' | 'all', label: string, count: number}>} */
  const filters = [
    { id: 'active', label: 'Active', count: activeCount },
    { id: 'completed', label: 'Completed', count: sorted.length - activeCount },
    { id: 'all', label: 'All', count: sorted.length },
  ];

  return (
    <main className="page narrow">
      <div className="crumbs"><a onClick={() => router.go({ view: 'landing' })}>~</a><span className="sep">/</span><span className="here">drafts</span></div>
      <div className="drafts-head">
        <h1>Drafts</h1>
        <span className="dh-sub">newest first · the changeset queue</span>
        <span className="dh-spacer" />
        <button className="ingest-btn" onClick={() => window.MYC_GO_INGEST(null)}><I.ingest width="15" height="15" />New from ingest</button>
      </div>

      <p style={{ marginBottom: 20, fontSize: 13 }}><a href="#/settings">AI settings</a></p>

      <div className="drafts-summary">
        <div className="ds-cell"><div className="ds-n write">{open.length}</div><div className="ds-l">open drafts</div></div>
        <div className="ds-cell"><div className="ds-n write">{pendingOps}</div><div className="ds-l">queued ops · dirty queue</div></div>
        <div className="ds-cell"><div className="ds-n">{submitted.length}</div><div className="ds-l">awaiting curator</div></div>
      </div>

      <div className="draft-filters" role="group" aria-label="Filter drafts">
        {filters.map(item => (
          <button key={item.id} className={`fchip${filter === item.id ? ' on' : ''}`}
            aria-pressed={filter === item.id} onClick={() => setFilter(item.id)}>
            {item.label}<span className="fc-ct">{item.count}</span>
          </button>
        ))}
      </div>

      {sorted.length === 0 ? <div style={{ marginTop: 24 }}><EmptyState title="No drafts yet" blurb="Ingest raw text or author a statement — every change stages here as a draft before it reaches the substrate." /></div> : shown.length === 0 ? (
        <EmptyState title={`No ${filter} drafts`} blurb={filter === 'active'
          ? 'No open or submitted drafts. Choose Completed or All to see closed drafts.'
          : 'Approved, rejected, and withdrawn drafts will appear here.'} />
      ) : (
        <div className="draft-list">
          {shown.map(d => (
            <div key={d.id} className="draft-row" onClick={() => router.go({ view: 'draft', id: d.id })}>
              <span className={`dr-dot ${d.status}`} />
              <div className="dr-body">
                <div className="dr-title">{d.title}</div>
                <DraftAssessment assessment={d.review_assessment} compact />
                <div className="dr-meta">
                  <span className="did">{d.id}</span><span>·</span><span>{d.origin}</span><span>·</span>
                  <span>{d.opCount} op{d.opCount === 1 ? '' : 's'}</span>
                </div>
              </div>
              <span className={`st-badge ${d.status}`}>{d.status}</span>
              <span className="dr-time">{relTime(d.createdAt)}</span>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}

Object.assign(window, { DraftReview, DraftsList, useMycDrafts });
window.MYC_OPEN_DRAFT_COUNT = () => (window.__MYC_DRAFTS || []).filter(d => d.status === 'open').length;
