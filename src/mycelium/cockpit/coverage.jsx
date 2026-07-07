// coverage.jsx — the Coverage map. Read-only join of the substrate against
// itself: every entity is a "topic", its bound subgraph is the set of
// statements that mention it. No editing from this surface — it is the map
// other people check, not a place to change the record.
//
// Re-grounded on REAL substrate signals (no mock backing): the coverage model
// is computed CLIENT-SIDE in a useEffect from window.MYCELIUM_DATA +
// window.MYCELIUM_INDEX, and the "what's missing" signal is the live list of
// OPEN knowledge gaps from Myc.knowledgeGaps('open'). The computed model is
// published to window.MYCELIUM_COVERAGE so app.jsx can read .summary.gaps for
// the topbar badge.
const { useState: useStateC, useEffect: useEffectC, useMemo: useMemoC, useRef: useRefC } = React;

/* ---------------- maturity vocabulary (derived from real signals) ---------------- */
// Maturity is NOT a human label here — it is DERIVED from the bound statement
// count: not-started (0) · stub (1-2) · partial (3-5) · solid (6+). The
// label/gloss/step map is local to this surface.
const MATURITY_META = {
  "not-started": { label: "not started", gloss: "No statement mentions this entity — declared on the map but undocumented.", step: 0 },
  stub: { label: "stub", gloss: "1–2 statements mention this entity — barely begun.", step: 1 },
  partial: { label: "partial", gloss: "3–5 statements mention this entity — taking shape.", step: 2 },
  solid: { label: "solid", gloss: "6+ statements mention this entity — substantially documented.", step: 4 },
};
function maturityFromCount(n) {
  if (n === 0) return "not-started";
  if (n <= 2) return "stub";
  if (n <= 5) return "partial";
  return "solid";
}

/* ---------------- model builder (PURE — real signals only) ---------------- */
// Connectivity over the bound subgraph: do the mentioning statements form one
// component when walked through window.MYCELIUM_DATA.links? 'single' (1 stmt),
// 'none' (0), 'connected' (one component), 'islands' (>1 component).
function connectivityOf(stmtIds, adjacency) {
  const n = stmtIds.length;
  if (n === 0) return { connectivity: "none", components: 0 };
  if (n === 1) return { connectivity: "single", components: 1 };
  const inSet = new Set(stmtIds);
  const seen = new Set();
  let components = 0;
  for (const start of stmtIds) {
    if (seen.has(start)) continue;
    components++;
    const stack = [start];
    seen.add(start);
    while (stack.length) {
      const cur = stack.pop();
      const neighbours = adjacency[cur] || [];
      for (const nb of neighbours) {
        if (inSet.has(nb) && !seen.has(nb)) { seen.add(nb); stack.push(nb); }
      }
    }
  }
  return { connectivity: components === 1 ? "connected" : "islands", components };
}

function buildCoverageModel(data, idx, openGapCount) {
  // Undirected adjacency over statement links (for connectivity walks).
  const adjacency = {};
  (data.links || []).forEach((l) => {
    (adjacency[l.from] = adjacency[l.from] || []).push(l.to);
    (adjacency[l.to] = adjacency[l.to] || []).push(l.from);
  });
  const layerOf = (kind) => {
    const def = idx.kindLayer[kind];
    return def ? def.layer : "descriptive";
  };

  const topics = (data.entities || []).map((e) => {
    const stmts = idx.mentionsByEntity[e.id] || [];
    const stmtIds = stmts.map((s) => s.id);

    // co-mentioned entities across the bound statements (distinct, minus self)
    const coEntities = new Set();
    stmts.forEach((s) => (s.mentions || []).forEach((eid) => { if (eid !== e.id) coEntities.add(eid); }));

    // layer mix over the bound statements
    let descriptive = false, prescriptive = false;
    stmts.forEach((s) => { layerOf(s.kind) === "prescriptive" ? (prescriptive = true) : (descriptive = true); });
    const mix = descriptive && prescriptive ? "mixed" : prescriptive ? "actionable-only" : descriptive ? "described-only" : "described-only";

    const conn = connectivityOf(stmtIds, adjacency);
    const maturity = maturityFromCount(stmts.length);

    return {
      id: e.id,
      title: e.name,
      desc: e.description || "",
      maturity,
      signals: {
        statements: stmts.length,
        entities: coEntities.size,
        mix,
        descriptive,
        prescriptive,
        actionable: prescriptive,
        connectivity: conn.connectivity,
        components: conn.components,
      },
      // The binding is just "entity → its mentioning statements" — a real,
      // confirmed relation. No suggested/similarity mock data exists.
      binding: { kind: stmts.length ? "bound" : "unbound", statements: stmtIds },
    };
  });

  const documented = topics.filter((t) => t.signals.statements > 0);
  const emptyTopics = topics.filter((t) => t.signals.statements === 0);
  const solid = documented.filter((t) => t.maturity === "solid").length;
  const partial = documented.filter((t) => t.maturity === "partial").length;
  const stub = documented.filter((t) => t.maturity === "stub").length;

  return {
    maturityMeta: MATURITY_META,
    topics,
    documented,
    emptyTopics,
    summary: {
      // app.jsx reads this for the topbar badge — OPEN knowledge gaps, the
      // genuine "what's missing" count.
      gaps: openGapCount,
      entities: topics.length,
      documented: documented.length,
      undocumented: emptyTopics.length,
      solid, partial, stub,
      totalStatements: (data.statements || []).length,
    },
  };
}

/* ---------------- small glyphs ---------------- */
function ConnGlyph({ kind }) {
  // connected: walkable chain · islands: broken · single/none: lone node
  if (kind === "connected") return (
    <svg className="conn-g" viewBox="0 0 22 12" fill="none" stroke="currentColor" strokeWidth="1.4">
      <line x1="4" y1="6" x2="11" y2="6" /><line x1="11" y1="6" x2="18" y2="6" />
      <circle cx="4" cy="6" r="2.2" fill="currentColor" stroke="none" /><circle cx="11" cy="6" r="2.2" fill="currentColor" stroke="none" /><circle cx="18" cy="6" r="2.2" fill="currentColor" stroke="none" />
    </svg>
  );
  if (kind === "islands") return (
    <svg className="conn-g" viewBox="0 0 22 12" fill="none" stroke="currentColor" strokeWidth="1.4">
      <line x1="4" y1="6" x2="8" y2="6" strokeDasharray="1.5 1.8" opacity="0.6" /><line x1="14" y1="6" x2="18" y2="6" strokeDasharray="1.5 1.8" opacity="0.6" />
      <circle cx="4" cy="6" r="2.2" fill="currentColor" stroke="none" /><circle cx="18" cy="6" r="2.2" fill="currentColor" stroke="none" />
    </svg>
  );
  return (
    <svg className="conn-g" viewBox="0 0 22 12" fill="none"><circle cx="11" cy="6" r="2.2" fill="currentColor" /></svg>
  );
}

const CONN_LABEL = { connected: "walkable", islands: "islands", single: "lone", none: "—" };

/* ---------------- auto signals (substrate EVIDENCE — quiet) ---------------- */
function AutoSignals({ signals, compact }) {
  const s = signals;
  if (s.statements === 0) {
    return (
      <div className="csig empty">
        <span className="nothing"><span className="n-glyph" />nothing documented</span>
      </div>
    );
  }
  const mixLabel = s.mix === "described-only" ? "described" : s.mix === "actionable-only" ? "actionable" : "mixed";
  return (
    <div className="csig">
      <span className="sig" title={`${s.statements} statement(s), ${s.entities} co-mentioned entit${s.entities === 1 ? "y" : "ies"} in the bound subgraph`}>
        <span className="sig-n">{s.statements}</span><span className="sig-l">stmt{s.statements === 1 ? "" : "s"}</span>
        <span className="sig-n" style={{ marginLeft: 4 }}>{s.entities}</span><span className="sig-l">ent</span>
      </span>
      {!compact && <span className="sig-sep" />}
      {!compact && (
        <span className="sig kmix" title={s.actionable ? "Has procedures/actions — not only descriptive facts" : "Descriptive facts only — no procedures or actions documented"}>
          <span className="kmix">
            <span className={`km ${s.descriptive ? "desc" : "off"}`} />
            <span className={`km ${s.prescriptive ? "pres" : "off"}`} />
          </span>
          <span className="kmix-label">{mixLabel}</span>
        </span>
      )}
      {!compact && <span className="sig-sep" />}
      {!compact && (
        <span className={`sig conn ${s.connectivity}`} title={s.connectivity === "connected" ? "One walkable chain" : s.connectivity === "islands" ? `${s.components} disconnected fragments` : "A single statement — nothing to traverse"}>
          <ConnGlyph kind={s.connectivity} />
          <span className="conn-label">{CONN_LABEL[s.connectivity]}</span>
        </span>
      )}
    </div>
  );
}

/* ---------------- maturity cell (DERIVED from the count — loud) ---------------- */
const TONE = { solid: "solid", partial: "partial", stub: "thin", "not-started": "gap" };
function MaturityCell({ maturity }) {
  const meta = MATURITY_META[maturity];
  const tone = TONE[maturity];
  const steps = 4;
  const onCount = meta.step < 0 ? 0 : meta.step;
  return (
    <div className="covcell">
      <div className={`mat-track ${tone}`}>
        {Array.from({ length: steps }).map((_, i) => (
          <span key={i} className={`mt-step${i < onCount ? " on" : ""}`} />
        ))}
      </div>
      <span className={`mat ${tone}`} title={meta.gloss}>
        <span className={`mat-glyph g-${tone}`} />{meta.label}
      </span>
    </div>
  );
}

/* ---------------- binding pill (real bound / honest unbound) ---------------- */
function BindPill({ binding }) {
  if (binding.kind === "unbound") return (
    <span className="bind unbound" title="No statement mentions this entity — nothing is bound.">unbound</span>
  );
  return (
    <span className="bind bound" title="Coverage tracks the statements that mention this entity — a real, derived binding.">
      <I.prov className="bind-g" />bound
    </span>
  );
}

/* ---------------- drawer (drill into bound subgraph, read-only) ---------------- */
function TopicDrawer({ topic }) {
  const router = useRouter();
  const idx = window.MYCELIUM_INDEX;
  const stmts = (topic.binding.statements || []).map((id) => idx.byId[id]).filter(Boolean);

  if (!stmts.length) {
    return (
      <div className="cov-drawer">
        <div className="cd-empty">
          <div className="cde-title">No statement mentions this entity.</div>
          <div className="cde-blurb">The entity exists in the substrate but nothing has been written about it yet. This is the gap — surfaced so it isn't mistaken for complete. Writing happens through ingest, then review; this surface only reports.</div>
          <div className="cd-actions" style={{ justifyContent: "center" }}>
            <button className="btn-sm find" onClick={() => router.go({ view: "entity", id: topic.id })}><I.arrow width="13" height="13" />Open this entity</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="cov-drawer">
      <div className="cd-banner">
        <span className="cdb-icon"><I.prov width="16" height="16" /></span>
        <span>Coverage tracks <b>{stmts.length} bound statement{stmts.length === 1 ? "" : "s"}</b> — the statements that mention this entity. Both maturity and the signals are derived from the substrate.</span>
      </div>
      {stmts.map((s) => (
        <div key={s.id} className="cd-stmt" onClick={() => router.go({ view: "statement", id: s.id })}>
          <KindTag kind={s.kind} />
          <div>
            <div className="cds-text">{s.text}</div>
            <div className="cds-id">{s.id}</div>
          </div>
          <I.arrow className="cds-arrow" width="15" height="15" />
        </div>
      ))}
      <div className="cd-actions">
        <button className="btn-sm find" onClick={() => router.go({ view: "entity", id: topic.id })}><I.arrow width="13" height="13" />Open this entity</button>
      </div>
    </div>
  );
}

/* ---------------- a topic row ---------------- */
function CoverageRow({ topic, open, onToggle, compact }) {
  const isGap = topic.signals.statements === 0;
  return (
    <div className="cov-rowwrap">
      <div className={`cov-row${open ? " is-open" : ""}${isGap ? " is-gap" : ""}`} onClick={onToggle}>
        <MaturityCell maturity={topic.maturity} />
        <div className="cov-tbody">
          <div className="cov-ttitle">{topic.title}</div>
          <div className="cov-tdesc">{topic.desc}</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 9 }}>
          <AutoSignals signals={topic.signals} compact={compact} />
          <BindPill binding={topic.binding} />
        </div>
        <span className="cov-chev"><I.arrow width="16" height="16" /></span>
      </div>
      {open && <TopicDrawer topic={topic} />}
    </div>
  );
}

/* ---------------- undocumented band (entities with zero mentioning statements) ---------------- */
function UndocumentedBand({ topics, onOpen }) {
  if (!topics.length) return null;
  return (
    <div className="cov-gapband">
      <div className="gb-head">
        <span className="gb-icon"><I.gap width="22" height="22" /></span>
        <div className="gb-titles">
          <div className="gb-title">Entities with <em>nothing</em> written about them</div>
          <div className="gb-desc">an entity exists in the substrate but no statement mentions it · absence, surfaced — not silence</div>
        </div>
        <span className="gb-count">{topics.length}</span>
      </div>
      <div className="gb-grid">
        {topics.map((t) => (
          <div key={t.id} className="gap-card" onClick={() => onOpen(t.id)}>
            <div className="gc-top">
              <span className="gc-title">{t.title}</span>
              <span className="gc-empty"><span className="ge-glyph" />0 stmts</span>
            </div>
            <div className="gc-desc">{t.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------- open knowledge gaps (the genuine "what's missing" signal) ---------------- */
// A knowledge gap is its own substrate record (id + text), NOT a statement — so
// there is no honest statement/entity to drill into. We surface id + text and
// leave it non-navigable rather than route to an id that won't resolve.
function KnowledgeGaps({ gaps }) {
  return (
    <div className="cov-untracked open">
      <div className="ut-head">
        <span className="ut-icon"><I.gap width="17" height="17" /></span>
        <div className="ut-titles">
          <div className="ut-title">Open knowledge gaps<span className="ut-badge">{gaps.length} open</span></div>
          <div className="ut-desc">Reported holes in what the substrate knows — questions asked that it couldn't answer. The genuine "what's missing" signal, straight from the substrate.</div>
        </div>
      </div>
      <div className="ut-body">
        {!gaps.length && <EmptyState title="No open knowledge gaps" blurb="Nothing has been reported as missing. The substrate has answered every question put to it so far." />}
        {gaps.map((g) => (
          <div key={g.id} className="ut-stmt" style={{ cursor: "default" }}>
            <span className="gc-empty"><span className="ge-glyph" />gap</span>
            <span className="us-text">{g.text}</span>
            <span className="cds-id">{g.id}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------- ledger ---------------- */
function Ledger({ summary, filter, onFilter }) {
  const total = summary.entities || 1;
  const pct = (n) => `${(n / total) * 100}%`;
  const seg = (key) => (filter === key ? " on" : "");
  return (
    <div className="cov-ledger">
      <div className="cov-meter" title="entities by derived maturity, plus undocumented and reported gaps">
        <span className="m-solid" style={{ width: pct(summary.solid) }} />
        <span className="m-partial" style={{ width: pct(summary.partial) }} />
        <span className="m-stub" style={{ width: pct(summary.stub) }} />
        <span className="m-gap" style={{ width: pct(summary.undocumented) }} />
      </div>
      <div className="cov-buckets">
        <button className={`cov-bucket b-doc${seg("documented")}`} onClick={() => onFilter(filter === "documented" ? "all" : "documented")}>
          <div className="cb-top"><span className="cb-dot" /><span className="cb-n">{summary.documented}</span></div>
          <span className="cb-l">Documented</span>
          <span className="cb-sub">{summary.solid} solid · {summary.partial} partial · {summary.stub} stub</span>
        </button>
        <button className={`cov-bucket b-gap${seg("undocumented")}`} onClick={() => onFilter(filter === "undocumented" ? "all" : "undocumented")}>
          <div className="cb-top"><span className="cb-dot" /><span className="cb-n">{summary.undocumented}</span></div>
          <span className="cb-l">Undocumented</span>
          <span className="cb-sub">entity · no mentioning statement</span>
        </button>
        <button className={`cov-bucket b-untracked${seg("gaps")}`} onClick={() => onFilter(filter === "gaps" ? "all" : "gaps")}>
          <div className="cb-top"><span className="cb-dot" /><span className="cb-n">{summary.gaps}</span></div>
          <span className="cb-l">Knowledge gaps</span>
          <span className="cb-sub">reported · open · unanswered</span>
        </button>
      </div>
      <div className="cov-ledger-foot">
        <span className="lf-dot" />
        <span><b>{summary.entities}</b> entit{summary.entities === 1 ? "y" : "ies"} treated as topics · <b>{summary.totalStatements}</b> statements in the substrate · maturity is derived from the mentioning-statement count, not a human label</span>
      </div>
    </div>
  );
}

/* ---------------- loading + error ---------------- */
function Loading({ elapsed }) {
  return (
    <div className="cov-loading">
      <div className="cov-load-bar">
        <span className="clb-orb"><span className="ring" /></span>
        <div className="clb-t">
          <div className="clb-title">Computing coverage and reading open knowledge gaps…</div>
          <div className="clb-sub">single-writer · naive · reads can stall under load</div>
        </div>
        <span className="clb-clock">{elapsed.toFixed(1)}s</span>
      </div>
      <div className="cov-skel">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="skel-row">
            <div><div className="skel s-track" /><div className="skel s-badge" /></div>
            <div><div className="skel s-title" /><div className="skel s-desc" /></div>
            <div className="skel s-sig" />
          </div>
        ))}
      </div>
    </div>
  );
}

function ErrorState({ message, onRetry }) {
  const role = /401|403|sign in|insufficient|forbidden|unauthor/i.test(message || "");
  return (
    <div className="cov-timeout">
      <div className="ct-icon"><I.timeout width="34" height="34" /></div>
      <div className="ct-title">{role ? "Sign in / insufficient role" : "Couldn't read the substrate"}</div>
      <div className="ct-blurb">
        {role
          ? "Reading open knowledge gaps requires a signed-in session with sufficient role. The coverage map couldn't be completed."
          : "The substrate didn't return the knowledge gaps. It is single-writer and deliberately naive, so reads can stall under load. Nothing is lost — try again."}
        {message ? <span style={{ display: "block", marginTop: 6, opacity: 0.7 }}>{message}</span> : null}
      </div>
      <button className="btn primary" onClick={onRetry}>Re-read substrate</button>
    </div>
  );
}

/* ---------------- the screen ---------------- */
function CoverageScreen() {
  const [phase, setPhase] = useStateC("loading"); // loading | ready | error
  const [elapsed, setElapsed] = useStateC(0);
  const [attempt, setAttempt] = useStateC(0);
  const [error, setError] = useStateC(null);
  const [model, setModel] = useStateC(null);
  const [gaps, setGaps] = useStateC([]);
  const [filter, setFilter] = useStateC("all"); // all | documented | undocumented | gaps
  const [sortMode, setSortMode] = useStateC("maturity"); // maturity | volume | name
  const [compact, setCompact] = useStateC(false);
  const [openId, setOpenId] = useStateC(null);
  const tickRef = useRefC(null);

  useEffectC(() => {
    let cancelled = false;
    setPhase("loading");
    setElapsed(0);
    setError(null);
    setOpenId(null);
    const t0 = Date.now();
    tickRef.current = setInterval(() => { if (!cancelled) setElapsed((Date.now() - t0) / 1000); }, 100);

    (async () => {
      try {
        const data = window.MYCELIUM_DATA;
        const idx = window.MYCELIUM_INDEX;
        const res = await window.Myc.knowledgeGaps("open");
        if (cancelled) return;
        const gapList = (res && res.gaps) || [];
        const m = buildCoverageModel(data, idx, gapList.length);
        // Publish the computed model so app.jsx can read .summary.gaps for the badge.
        window.MYCELIUM_COVERAGE = m;
        setModel(m);
        setGaps(gapList);
        setPhase("ready");
      } catch (e) {
        if (cancelled) return;
        // Even on a gap-read failure we still publish a coverage model so the
        // rest of the cockpit (the badge) has the entity-derived signals.
        try {
          const m = buildCoverageModel(window.MYCELIUM_DATA, window.MYCELIUM_INDEX, 0);
          window.MYCELIUM_COVERAGE = m;
          setModel(m);
        } catch (_) { /* data not yet live — leave model null */ }
        setError(e && e.message ? e.message : "read failed");
        setPhase("error");
      } finally {
        if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; }
      }
    })();

    return () => { cancelled = true; if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; } };
  }, [attempt]);

  const reload = () => setAttempt((a) => a + 1);
  const openTopic = (id) => setOpenId((prev) => (prev === id ? null : id));

  // which topics show, given the bucket filter
  const pool = useMemoC(() => {
    if (!model) return [];
    if (filter === "documented") return model.documented;
    if (filter === "undocumented") return model.emptyTopics;
    return model.topics; // all (gaps handled separately, they aren't topics)
  }, [model, filter]);

  const sorted = useMemoC(() => {
    const arr = [...pool];
    if (sortMode === "maturity") {
      const rank = { solid: 0, partial: 1, stub: 2, "not-started": 3 };
      arr.sort((a, b) => (rank[a.maturity] - rank[b.maturity]) || (b.signals.statements - a.signals.statements));
    } else if (sortMode === "volume") {
      arr.sort((a, b) => b.signals.statements - a.signals.statements);
    } else {
      arr.sort((a, b) => a.title.localeCompare(b.title));
    }
    return arr;
  }, [pool, sortMode]);

  if (phase === "loading") return (
    <main className="page coverage">
      <CoverageHeader onReload={reload} loading />
      <Loading elapsed={elapsed} />
    </main>
  );
  if (phase === "error" && !model) return (
    <main className="page coverage">
      <CoverageHeader onReload={reload} />
      <ErrorState message={error} onRetry={reload} />
    </main>
  );

  const summary = model.summary;
  const showGapBand = filter === "all" || filter === "undocumented";
  const showList = filter !== "gaps";
  const showGaps = filter === "all" || filter === "gaps";

  return (
    <main className="page coverage">
      <CoverageHeader onReload={reload} />
      {phase === "error" && (
        <div className="cov-ledger-foot" style={{ marginBottom: 12, border: "1px solid var(--line)", borderRadius: "var(--r-md)" }}>
          <span className="lf-dot" style={{ background: "var(--warn)" }} />
          <span>Coverage is derived from local substrate data, but the <b>open knowledge gaps couldn't be read</b> ({error}). The gap count may be stale.</span>
        </div>
      )}
      <Ledger summary={summary} filter={filter} onFilter={(f) => { setFilter(f); setOpenId(null); }} />

      {/* controls */}
      <div className="cov-controls">
        <div className="cov-seg">
          <span className="seg-label">sort</span>
          <button className={sortMode === "maturity" ? "on" : ""} onClick={() => setSortMode("maturity")}>maturity</button>
          <button className={sortMode === "volume" ? "on" : ""} onClick={() => setSortMode("volume")}>volume</button>
          <button className={sortMode === "name" ? "on" : ""} onClick={() => setSortMode("name")}>name</button>
        </div>
        <div className="cov-seg">
          <span className="seg-label">cell</span>
          <button className={!compact ? "on" : ""} onClick={() => setCompact(false)}>full</button>
          <button className={compact ? "on" : ""} onClick={() => setCompact(true)}>compact</button>
        </div>
      </div>

      {sortMode === "volume" && (
        <div className="cov-ledger-foot" style={{ marginTop: 12, border: "1px solid var(--line)", borderRadius: "var(--r-md)" }}>
          <span className="lf-dot" style={{ background: "var(--warn)" }} />
          <span>Ranked by statement count — <b>volume is not a measure of quality.</b> A high count never implies the topic is well documented; read the maturity badge, not the number.</span>
        </div>
      )}

      {showGapBand && <UndocumentedBand topics={model.emptyTopics} onOpen={(id) => { setFilter("all"); setSortMode("maturity"); setOpenId(id); }} />}

      {showList && (
        <div className="cov-section">
          <div className="cov-sec-head">
            <span className="csh-title">
              {filter === "documented" ? "Documented entities" : filter === "undocumented" ? "Undocumented entities" : "Entities as topics"}
            </span>
            <span className="csh-count">{sorted.length} shown</span>
          </div>

          {sorted.map((t) => (
            <CoverageRow key={t.id} topic={t} compact={compact} open={openId === t.id} onToggle={() => openTopic(t.id)} />
          ))}

          {!sorted.length && <EmptyState title="No entities here" blurb="No entities fall in this bucket. Clear the filter to widen the view." />}
        </div>
      )}

      {showGaps && <KnowledgeGaps gaps={gaps} />}
    </main>
  );
}

function CoverageHeader({ onReload, loading }) {
  return (
    <div className="cov-head">
      <div className="cov-eyebrow">Mycelium · documentation map</div>
      <h1 className="cov-title">What's <em>documented</em> — and what isn't, yet.</h1>
      <p className="cov-sub">
        Every entity in the substrate, treated as a topic, laid over what the substrate <b>actually</b> holds about it. Three things fall out: what's covered and how deeply (derived from the count of statements that mention it), the entities <b>nobody has written about</b> yet, and the <b>open knowledge gaps</b> that have been reported. A read-only map — writing happens through ingest, then review.
        {!loading && <button className="btn-sm" style={{ marginLeft: 12, verticalAlign: "middle" }} onClick={onReload}><I.timeout width="13" height="13" />Re-read substrate</button>}
      </p>
    </div>
  );
}

window.CoverageScreen = CoverageScreen;
