// api.js — live backend bridge for the cockpit.
//
// Every HTTP call and every backend→view-shape adaptation lives here. The
// surface .jsx files call window.Myc.* and never fetch directly, exactly the
// way the read-only /ui keeps its loader in data.js. The cockpit components
// were authored against a richer mock; this layer maps the real substrate
// endpoints onto the shapes those components already expect.
//
// Endpoints used (all live, role-gated by the session cookie / bearer token):
//   GET  /api/data                      — whole-substrate dump
//   GET  /list-statement-kinds          — kind vocabulary (no `layer`; mapped below)
//   GET  /list-link-types               — statement-link vocabulary
//   GET  /list-entity-link-types        — entity-link vocabulary
//   POST /search-statements             — semantic Find (scored)
//   POST /survey-statements             — multi-part Find (scored)
//   POST /grep-statements               — literal Find (no score; alias-aware)
//   POST /ask                           — agentic answer (answered | needs_clarification)
//   POST /ingest                        — raw text → draft (writer role; long-running)
//   POST /start-research                — research topic → async draft run
//   GET  /list-research-runs            — newest-first research run list
//   POST /get-research-run              — one research run by id
//   GET  /list-research-sources         — configured research sources
//   GET/POST/PATCH/DELETE /api/drafts/* — draft spine
//   GET  /api/knowledge-gaps            — reported gaps (Coverage)

(function () {
  // Kinds carry no `layer` over the wire, but the layer split is a stable part
  // of the domain taxonomy (descriptive facts vs. prescriptive how-to). The
  // cockpit colours by layer, so map it here; unknown kinds default descriptive.
  const KIND_LAYER = {
    event: 'descriptive', state: 'descriptive', capability: 'descriptive',
    rule: 'descriptive', property: 'descriptive',
    procedure: 'prescriptive', action: 'prescriptive', check: 'prescriptive', cause: 'prescriptive',
  };
  const layerOf = (kind) => KIND_LAYER[kind] || 'descriptive';

  /* ----------------------------- transport ----------------------------- */
  async function http(method, path, body) {
    const opts = { method, headers: { accept: 'application/json' }, credentials: 'same-origin' };
    if (body !== undefined) {
      opts.headers['content-type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    if (!res.ok) {
      let detail = res.status + ' ' + res.statusText;
      try { const j = await res.json(); if (j && j.detail) detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch (e) { /* non-json body */ }
      const err = new Error(detail);
      err.status = res.status;
      err.path = path;
      throw err;
    }
    if (res.status === 204) return null;
    const ct = res.headers.get('content-type') || '';
    return ct.includes('json') ? res.json() : res.text();
  }
  const get = (p) => http('GET', p);
  const post = (p, b) => http('POST', p, b || {});

  // Backend records have no title; the first sentence is the human handle.
  // (The read-only /ui derives titles the same way.)
  function titleOf(text) {
    const first = String(text || '').split(/(?<=\.)\s+/)[0];
    return first.length > 96 ? first.slice(0, 93) + '…' : first;
  }

  /* --------------------------- substrate load --------------------------- */
  // Builds window.MYCELIUM_DATA in the exact shape lib.jsx/buildIndex expects:
  //   { entities:[{id,name,description}], names:[{id,text,entity}],
  //     statements:[{id,kind,text,title,mentions:[entityId]}],
  //     links:[{from,to,type,when?}], entityLinks:[{from,to,type}],
  //     statementKinds:[{name,layer,gloss}], linkTypes, entityLinkTypes }
  async function loadData() {
    // NB: /api/data is a hand-written GET, but the vocabulary endpoints are
    // auto-mirrored MCP tools — registered as POST (every tool carries an
    // injected optional draft_id param), not GET.
    const [dump, kinds, linkTypes, entityLinkTypes] = await Promise.all([
      get('/api/data'),
      post('/list-statement-kinds', {}).catch(() => []),
      post('/list-link-types', {}).catch(() => []),
      post('/list-entity-link-types', {}).catch(() => []),
    ]);

    const statements = (dump.statements || []).map((s) => ({
      id: s.id, kind: s.kind, text: s.text, mentions: s.mentions || [], title: titleOf(s.text),
    }));
    // dump links use `link_type`; the components read `type`. `when` is a
    // boolean tree ({all|any:[stmtId]}) and passes through untouched.
    const links = (dump.links || []).map((l) => ({ from: l.from, to: l.to, type: l.link_type, when: l.when }));
    const entityLinks = (dump.entity_links || []).map((l) => ({ from: l.from, to: l.to, type: l.link_type }));

    const statementKinds = (kinds || []).map((k) => ({
      name: k.kind, layer: layerOf(k.kind), gloss: k.description || k.when_to_use || '', usageCount: k.usage_count,
    }));
    // Guarantee every kind a statement actually uses exists in the vocab, so
    // KindTag/layer lookups never fall through to "unknown".
    const known = new Set(statementKinds.map((k) => k.name));
    statements.forEach((s) => {
      if (s.kind && !known.has(s.kind)) {
        known.add(s.kind);
        statementKinds.push({ name: s.kind, layer: layerOf(s.kind), gloss: '' });
      }
    });

    const data = {
      entities: dump.entities || [],
      names: dump.names || [],
      statements,
      links,
      entityLinks,
      annotations: dump.annotations || [],
      statementKinds,
      linkTypes: (linkTypes || []).map((t) => ({ name: t.link_type, gloss: t.description || '' })),
      entityLinkTypes: (entityLinkTypes || []).map((t) => ({ name: t.link_type, gloss: t.description || '' })),
    };
    window.MYCELIUM_DATA = data;
    return data;
  }

  /* -------------------------------- Find -------------------------------- */
  // Returns { mode, rows:[{ id, statement:{id,kind,text}, score|null, via?, occ? }] }.
  // Semantic/survey carry a real relevance score; grep is deterministic and
  // alias-aware (matched_via) with a real occurrence count but no score.
  async function find(mode, query) {
    const q = (query || '').trim();
    if (!q) return { mode, rows: [] };

    if (mode === 'grep') {
      const r = await post('/grep-statements', { query: q, limit: 80 });
      const needle = q.toLowerCase();
      const rows = (r.statements || []).map((s) => {
        const hay = String(s.text || '').toLowerCase();
        let i = 0, n = 0;
        while ((i = hay.indexOf(needle, i)) !== -1) { n++; i += needle.length; }
        return { id: s.id, statement: { id: s.id, kind: s.kind, text: s.text }, via: s.matched_via, occ: n, score: null };
      });
      // text hits (with occurrences) first, alias-only hits after.
      rows.sort((a, b) => (b.occ || 0) - (a.occ || 0));
      return { mode, rows, total: r.total };
    }

    const path = mode === 'survey' ? '/survey-statements' : '/search-statements';
    const body = mode === 'survey' ? { query: q, k: 6 } : { query: q, limit: 14 };
    const list = await post(path, body);
    const rows = (Array.isArray(list) ? list : [])
      .filter((s) => s && s.id && typeof s.score === 'number') // drop unscored depth-expansions
      .map((s) => ({ id: s.id, statement: { id: s.id, kind: s.kind, text: s.text }, score: s.score }));
    rows.sort((a, b) => b.score - a.score);
    return { mode, rows };
  }

  /* -------------------------------- Ask --------------------------------- */
  // Adapts the real /ask discriminated union onto the cockpit's Answered /
  // NeedsClarification shapes. The backend never emits a `timeout` outcome —
  // budget exhaustion comes back as an `answered` with confidence forced to
  // `low` and trace.forced_finalize set, which we surface as `degraded`. A real
  // transport failure (the fetch itself) is what drives the timeout/error UI.
  const CONF_VALUE = { high: 0.85, medium: 0.6, low: 0.35 };

  function splitParas(answer) {
    const text = String(answer || '').trim();
    if (!text) return ['The substrate returned no prose for this question.'];
    const paras = text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
    return paras.length ? paras : [text];
  }
  function shortLabel(s) {
    const words = String(s || '').trim().split(/\s+/);
    const head = words.slice(0, 7).join(' ');
    return words.length > 7 ? head + '…' : head || 'Interpretation';
  }
  function splitKnown(known) {
    if (Array.isArray(known)) return known.filter(Boolean);
    const text = String(known || '').trim();
    if (!text) return [];
    return text.split(/(?<=[.!?])\s+(?=[A-Z0-9])/).map((s) => s.trim()).filter(Boolean);
  }
  function confRationale(raw, degraded) {
    const n = (raw.gaps || []).length;
    const base = n
      ? `Grounded in the cited statements; ${n} explicit gap${n === 1 ? '' : 's'} lowered confidence.`
      : 'Grounded directly in the cited statements.';
    return degraded
      ? base + ' The loop was force-finalised under load — treat this answer as provisional.'
      : base;
  }
  function buildTrace(trace, provenance) {
    const t = trace || {};
    const steps = [];
    const tools = Array.isArray(t.tool_calls) ? t.tool_calls : [];
    steps.push({
      phase: 'recon',
      detail: `Read "${t.question || ''}" with ${t.model || 'the model'} — ${t.op_count || 0} retrieval op${t.op_count === 1 ? '' : 's'} against the substrate.`,
      refs: [],
    });
    const ledger = Array.isArray(t.sub_question_ledger) ? t.sub_question_ledger : [];
    if (ledger.length) {
      steps.push({
        phase: 'traverse',
        detail: ledger.map((l) => `• ${l.sub_question}${l.status ? ` (${l.status})` : ''}`).join('  '),
        refs: [],
      });
    } else if (tools.length) {
      const names = [...new Set(tools.map((c) => c.name).filter(Boolean))];
      steps.push({ phase: 'traverse', detail: `Called ${tools.length} tool${tools.length === 1 ? '' : 's'}: ${names.join(', ')}.`, refs: [] });
    }
    steps.push({
      phase: 'synthesis',
      detail: `Composed the answer${t.degraded || t.forced_finalize ? ' (degraded — forced finalize)' : ''}.`,
      refs: provenance || [],
    });
    return steps;
  }

  function adaptAsk(raw, question) {
    if (!raw || raw.outcome === 'needs_clarification') {
      const cands = (raw && raw.candidates) || [];
      return {
        outcome: 'needs_clarification',
        question,
        clarifyingQuestion: (raw && raw.question) || 'Which reading did you mean?',
        interpretations: cands.map((c) => ({
          label: shortLabel(c.interpretation),
          note: c.interpretation || '',
          wouldRetrieve: c.would_pull ? [].concat(c.would_pull) : [],
        })),
        known: splitKnown(raw && raw.known_so_far),
      };
    }
    const idx = window.MYCELIUM_INDEX || { byId: {} };
    const conf = raw.confidence || 'low';
    const degraded = !!(raw.trace && (raw.trace.forced_finalize || raw.trace.degraded));
    const interp = raw.interpretation || {};
    return {
      outcome: 'answered',
      question,
      degraded,
      interpretation: {
        text: interp.resolved_to || interp.as_asked || question,
        reframed: !!interp.reframed,
        reframedNote: interp.reframe_reason || 'reframed against what the substrate actually holds',
      },
      confidence: { level: conf, value: CONF_VALUE[conf] != null ? CONF_VALUE[conf] : 0.35, rationale: confRationale(raw, degraded) },
      answer: splitParas(raw.answer),
      gaps: raw.gaps || [],
      provenance: (raw.provenance || []).map((id) => ({ id, role: (idx.byId[id] && idx.byId[id].kind) || 'statement' })),
      trace: buildTrace(raw.trace, raw.provenance || []),
    };
  }

  async function ask(question) {
    const raw = await post('/ask', { question });
    return adaptAsk(raw, question);
  }

  /* --------------------------- Edit statement text --------------------------- */
  // Save a new statement text through the real write path (replace_text: text
  // only, re-embeds, re-derives mentions, leaves links/kind untouched). The
  // substrate decides live-vs-draft by role: writer/admin write live; a drafter
  // auto-stages a draft op. We classify the response so the UI can report which
  // happened. `force` retries past a phrasing-catalog rejection.
  // Returns one of:
  //   { status:'saved',    statementId, warnings? }
  //   { status:'staged',   draftId, seq }
  //   { status:'rejected', violations }
  async function editStatement(id, text, force) {
    const raw = await post('/replace-text', { id, text, allow_phrasing_violations: !!force });
    if (raw && raw.rejected) return { status: 'rejected', violations: raw.violations || [] };
    if (raw && raw.draft_id && raw.queued) return { status: 'staged', draftId: raw.draft_id, seq: raw.seq };
    return { status: 'saved', statementId: (raw && raw.statement_id) || id, warnings: (raw && raw.phrasing_violations) || null };
  }

  // After a LIVE edit, patch the cached statement (text/kind/title + re-derived
  // mentions) in MYCELIUM_DATA + MYCELIUM_INDEX so already-open views reflect
  // the change without a full substrate reload.
  async function refreshStatement(id) {
    const res = await post('/get-statements', { ids: [id] });
    const rec = ((res && res.statements) || []).find((s) => s && s.id === id);
    if (!rec) return null;
    const mentions = [];
    (rec.mentions || []).forEach((m) => { if (m.entity_id && mentions.indexOf(m.entity_id) < 0) mentions.push(m.entity_id); });
    const title = titleOf(rec.text);
    const data = window.MYCELIUM_DATA, idx = window.MYCELIUM_INDEX;
    if (data) {
      const s = data.statements.find((x) => x.id === id);
      if (s) { s.text = rec.text; s.kind = rec.kind; s.title = title; s.mentions = mentions; }
    }
    if (idx && idx.byId[id]) {
      const e = idx.byId[id];
      e.text = rec.text; e.kind = rec.kind; e.title = title; e.mentions = mentions;
    }
    return { id, text: rec.text, kind: rec.kind, title, mentions };
  }

  /* ------------------------------- expose ------------------------------- */
  window.Myc = {
    get, post, http, titleOf, layerOf,
    loadData,
    find,
    ask,
    editStatement,
    refreshStatement,
    // Ingest is a long-running write (up to ~120s) that persists a draft and
    // returns { outcome:'draft_created', draft_id, ops, flagged, ... } or
    // { outcome:'nothing_to_ingest', reason }. Caller routes to the draft.
    ingest: (text) => post('/ingest', { text }),
    research: {
      start: (topic, source) => post('/start-research', source ? { topic, source } : { topic }),
      list: () => get('/list-research-runs').then(r => (r && r.runs) || []),
      get: (id) => post('/get-research-run', { run_id: id }),
      sources: () => get('/list-research-sources').then(r => (r && r.sources) || []),
    },
    // Raw draft REST — drafts.jsx owns the op-shape adaptation/rendering.
    drafts: {
      list: (status) => get('/api/drafts?status=' + encodeURIComponent(status || 'all')),
      get: (id) => get('/api/drafts/' + encodeURIComponent(id)),
      discardOp: (id, seq) => http('DELETE', '/api/drafts/' + encodeURIComponent(id) + '/ops/' + seq),
      submit: (id) => post('/api/drafts/' + encodeURIComponent(id) + '/submit'),
      withdraw: (id) => post('/api/drafts/' + encodeURIComponent(id) + '/withdraw'),
    },
    knowledgeGaps: (status) => get('/api/knowledge-gaps?status=' + encodeURIComponent(status || 'open')),
    // Derived-mention review queue. A match on a short/ambiguous entity name is
    // held for per-occurrence human judgement: approve → materialize the real
    // mention, reject → write nothing. HTTP-only (deliberately not an MCP tool).
    pendingMentions: (status, limit, offset) =>
      get('/api/pending-mentions?status=' + encodeURIComponent(status || 'open')
        + '&limit=' + (limit || 200) + '&offset=' + (offset || 0))
        .then((r) => (r && r.pending_mentions) || []),
    actOnMention: (id, action) =>
      http('PATCH', '/api/pending-mentions/' + encodeURIComponent(id), { action }),
    // Vocabulary edits that make the matcher derive new mentions. Creating an
    // entity or attaching an alias enqueues a recompute-scan server-side, so any
    // existing statement whose text contains the new name picks up the mention
    // on the next worker drain — no per-statement wiring needed here.
    upsertEntity: (name, description) =>
      post('/upsert-entity', { name, description: description || '' }),
    upsertName: (text, entityId) =>
      post('/upsert-name', { text, entity_id: entityId }),
    me: () => get('/api/me'),
  };
})();
