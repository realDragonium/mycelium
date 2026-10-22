// Force-directed graph view for Mycelium.

const { useState: useStateG, useEffect: useEffectG, useRef: useRefG, useMemo: useMemoG, useCallback: useCallbackG } = React;

// Walk a when-clause tree and yield every leaf statement_id. Tolerates the
// legacy flat-string form. Same shape as the helper in components.jsx —
// duplicated here so this file stays standalone.
function* walkWhenLeavesG(when) {
  if (!when) return;
  if (typeof when === 'string') { yield when; return; }
  if (when.statement_id) { yield when.statement_id; return; }
  if (when.op && Array.isArray(when.of)) {
    for (const child of when.of) yield* walkWhenLeavesG(child);
  }
}

const LINK_TYPE_COLORS_LIGHT = {
  'contains':   '#6b3a8c',
  'triggers':   '#b14b1f',
  'enables':    '#2f6b51',
  'requires':   '#7c2f2a',
  'precedes':   '#4a5d8a',
  'implies':    '#6e5a1c',
  'uses':       '#355e3b',
  'follows':    '#4a5d8a',
  'depends-on': '#7c2f2a',
  'constrains': '#5a4a3a',
  'links-to':   '#6e5a1c',
  'mentions':   '#94897a',
  'describes':  '#0d9488',
  'applies-to': '#b45309',
  'involves':   '#7c3aed',
};
const LINK_TYPE_COLORS_DARK = {
  'contains':   '#c9a8e0',
  'triggers':   '#e8a385',
  'enables':    '#93c19d',
  'requires':   '#d99183',
  'precedes':   '#98abd1',
  'implies':    '#d4ba6e',
  'uses':       '#93c19d',
  'follows':    '#98abd1',
  'depends-on': '#d99183',
  'constrains': '#c9bca0',
  'links-to':   '#d4ba6e',
  'mentions':   '#6e6757',
  'describes':  '#5eead4',
  'applies-to': '#fcd34d',
  'involves':   '#c4b5fd',
};

// One synthetic statement→entity edge type per claim kind. New kinds
// added to the substrate fall through to `mentions` (visible but
// neutral grey-dashed) until they're registered here, at which point
// they get their own color and default-on visibility. Single source of
// truth so the renderer, the toolbar, the activeTypes default, and the
// side-panel neighbor list never disagree.
const STMT_ENTITY_EDGE_BY_KIND = {
  state:      'describes',
  capability: 'applies-to',
  event:      'involves',
};
const stmtEntityEdgeType = (claimKind) => STMT_ENTITY_EDGE_BY_KIND[claimKind] || 'mentions';
const KNOWN_STMT_ENTITY_TYPES = new Set(Object.values(STMT_ENTITY_EDGE_BY_KIND));

// `data` and `index` are optional — when omitted, GraphView reads the
// full substrate from the globals (the original behaviour). Callers
// that want a scoped view (e.g. drafts detail) pass their own dataset
// and matching `buildIndex(data)` result. Same component, same drawing
// + interaction code path — no parallel renderer to drift out of sync.
//
// `embedded` switches the surrounding chrome — drops the 320px detail
// sidepanel and uses the parent container's height instead of a viewport
// calc. Use it when GraphView is mounted inside a smaller area (the
// draft detail page, future inline-graph spots). The canvas itself and
// every interaction stay identical.
function GraphView({ focusId, data: dataProp, index: indexProp, embedded = false }) {
  const router = useRouter();
  const { tweaks } = React.useContext(TweaksCtx);
  const data = dataProp || window.MYCELIUM_DATA;
  const idx = indexProp || window.MYCELIUM_INDEX;

  const canvasRef = useRefG(null);
  const containerRef = useRefG(null);
  const [hoverId, setHoverId] = useStateG(null);
  const [selectedId, setSelectedId] = useStateG(focusId || null);
  const [focusMode, setFocusMode] = useStateG(false);
  const [showEntities, setShowEntities] = useStateG(true);
  const [showStatements, setShowStatements] = useStateG(true);
  const [searchQuery, setSearchQuery] = useStateG('');

  // Set of node ids that match the current search query — entities by
  // any of their names, statements by title/text. Case-insensitive
  // substring match. Empty when the query is blank.
  const searchMatches = useMemoG(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return null;
    const set = new Set();
    for (const e of data.entities) {
      const names = (idx.namesByEntity[e.id] || []).map(n => n.text);
      const hay = [e.name, e.description || '', ...names].join(' ').toLowerCase();
      if (hay.includes(q)) set.add(e.id);
    }
    for (const b of data.statements) {
      const hay = ((b.title || '') + ' ' + (b.text || '')).toLowerCase();
      if (hay.includes(q)) set.add(b.id);
    }
    return set;
  }, [searchQuery, data]);
  const [activeTypes, setActiveTypes] = useStateG(() => {
    // Statement→entity mention is structural for every claim kind: a
    // state, capability, or event without its mentioned entities reads
    // as floating. So all registered per-kind edge types are on by
    // default. The plain `mentions` fallback (used only for unknown
    // kinds) stays opt-in so a new kind can't suddenly fill the canvas
    // with un-styled noise before it gets its own entry in
    // STMT_ENTITY_EDGE_BY_KIND.
    const s = new Set();
    data.links.forEach(l => s.add(l.link_type));
    (data.entity_links || []).forEach(l => s.add(l.link_type));
    KNOWN_STMT_ENTITY_TYPES.forEach(t => s.add(t));
    return s;
  });

  // When new link types appear in the data (after an authoring round-trip
  // or a server data refresh), surface them as visible-by-default so they
  // don't silently hide. Existing user toggle decisions are preserved —
  // we only ADD newly-seen types.
  useEffectG(() => {
    const seen = new Set();
    data.links.forEach(l => seen.add(l.link_type));
    (data.entity_links || []).forEach(l => seen.add(l.link_type));
    setActiveTypes(prev => {
      let changed = false;
      const next = new Set(prev);
      for (const t of seen) {
        if (!next.has(t)) { next.add(t); changed = true; }
      }
      return changed ? next : prev;
    });
  }, [data]);

  // Build node list once
  const { nodes, edges } = useMemoG(() => {
    const nodes = [];
    data.statements.forEach(b => nodes.push({
      id: b.id, kind: 'statement', claimKind: b.kind,
      label: b.title || b.text.slice(0, 60),
    }));
    data.entities.forEach(e => nodes.push({ id: e.id, kind: 'entity', label: e.name }));

    const edges = [];
    data.links.forEach(l => edges.push({
      source: l.from, target: l.to, link_type: l.link_type, kind: 'statement',
      when: l.when,  // carried so the renderer can draw condition connectors
    }));
    // Statement→entity edges. Every mention is structural: a claim of
    // any kind without its mentioned entities reads as floating. Edge
    // *type* is per kind (describes / applies-to / involves) so the
    // renderer can color-code them and the toolbar can toggle each
    // independently — but the existence of a line doesn't depend on
    // the kind. New kinds inherit the dashed grey `mentions` fallback
    // until they earn their own type in STMT_ENTITY_EDGE_BY_KIND.
    data.statements.forEach(b => {
      const link_type = stmtEntityEdgeType(b.kind);
      (b.mentions || []).forEach(eid => edges.push({
        source: b.id, target: eid, link_type, kind: 'mention',
      }));
    });
    // Entity↔entity edges (parent/subsidiary, kind-of, partner-of, etc.).
    // Tagged with kind: 'entity' so we can render them distinctly from
    // statement-links — typically slightly thicker and drawn last so
    // structural relationships read above the statement cloud.
    (data.entity_links || []).forEach(l => edges.push({
      source: l.from, target: l.to, link_type: l.link_type, kind: 'entity',
    }));
    return { nodes, edges };
  }, [data]);

  // Focus neighborhood set
  const neighborhood = useMemoG(() => {
    if (!focusMode || !selectedId) return null;
    const set = new Set([selectedId]);
    edges.forEach(e => {
      if (e.source === selectedId) set.add(e.target);
      if (e.target === selectedId) set.add(e.source);
    });
    return set;
  }, [focusMode, selectedId, edges]);

  // Simulation state — kept in refs so we can animate without re-render
  const simRef = useRefG(null);

  // Pre-baked entity positions (shared with the entities-only view).
  // Fetch once; bump positionsTick when loaded so the main effect re-runs
  // and seeds entities from the baked layout instead of the BFS-phyllotaxis
  // fallback.
  const positionsRef = useRefG(null);
  const [positionsTick, setPositionsTick] = useStateG(0);
  useEffectG(() => {
    let cancelled = false;
    const finalise = (map) => {
      if (cancelled) return;
      // Always set positionsRef (even to an empty map on failure) so the
      // main effect's "wait for positions" gate releases. Without this,
      // a missing/broken JSON would block the graph from ever rendering.
      positionsRef.current = { map: map || {} };
      setPositionsTick(t => t + 1);
    };
    fetch('/api/entity-positions')
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (!d) return finalise(null);
        const map = {};
        for (const n of (d.nodes || [])) {
          map[n.id] = { x: n.x, y: n.y };
        }
        finalise(map);
      })
      .catch(() => finalise(null));
    return () => { cancelled = true; };
  }, []);

  useEffectG(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    let width = container.clientWidth;
    let height = container.clientHeight;
    const resize = () => {
      width = container.clientWidth;
      height = container.clientHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = width + 'px';
      canvas.style.height = height + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(container);

    // Initialize positions if not present.
    //
    // Initial spawn is a phyllotaxis (sunflower-seed) spiral: uniform
    // 2D density that scales with N. The previous "ring of radius 180"
    // packed every node onto a 1130px circumference — at 2200 nodes
    // that's ~0.5px between neighbors, which the 1200/d² repulsion
    // turns into a four-digit force and the integrator turns into a
    // 100+ px-per-frame position jump. Visually the graph "explodes"
    // before settling. Phyllotaxis keeps nearest-neighbor distance
    // ≈ SPAWN_SPACING regardless of N.
    //
    // Spiral SLOTS are shuffled before assigning to nodes so kinds
    // intermix from the start. Without the shuffle, slot-i = node-i
    // means whichever kind comes later in the `nodes` array (entities,
    // built after statements) gets the outer-ring slots, producing a
    // visible "statements inside, entities ringing them" layout that
    // springs can't break apart once repulsion settles.
    // Wait for the baked entity positions to load before the first
    // sim init. The fetch handler always finalises (with an empty map
    // on failure) and bumps positionsTick, which re-runs this effect,
    // so this early-return can't deadlock the view.
    if (!positionsRef.current) return;

    if (!simRef.current) {
      // Entity-anchored seed:
      //
      // Phyllotaxis spawned every node near the canvas center, so the
      // simulation only ever pulled inward — converging on a central
      // blob with everything fighting for the middle. Instead, we
      // pre-compute a layout that already has structure on frame 1:
      //
      //   1. Entities are placed across a generous canvas with a
      //      minimum-distance check (Poisson-disk style retry). This
      //      gives entity nodes "personal space" before any force runs.
      //   2. Statements spawn near the centroid of their mentioned
      //      entities, with a small jitter. A statement that mentions
      //      one entity sits next to it; one mentioning two entities
      //      sits between them.
      //   3. Statements with no mentions spawn jittered around the
      //      centroid of all entities — they have nothing to anchor to.
      //
      // The simulation then *polishes* this layout instead of
      // assembling it from chaos. Local clusters already exist; the
      // sim just settles spacing and resolves overlaps.
      // Spread the initial spawn area with sqrt(N): area grows linearly
      // with node count so per-node density stays roughly constant
      // regardless of graph size. Anchored to a baseline that suits
      // small graphs (~200 nodes) without leaving them sparse.
      const SPREAD_REF_N = 200;
      const spreadScale = Math.sqrt(Math.max(1, nodes.length) / SPREAD_REF_N);
      // Embedded view runs on a small viewport (the draft detail card)
      // and almost always shows a handful of nodes. Tighter spawn +
      // spring rest keeps everything readable in the box rather than
      // spreading out to fill thousands of virtual pixels the user
      // never sees.
      const COMPACT_MULT = embedded ? 0.45 : 1;
      const SPREAD_W = Math.max(2400, width * 1.8) * spreadScale * COMPACT_MULT;
      const SPREAD_H = Math.max(1800, height * 1.8) * spreadScale * COMPACT_MULT;
      const ORIGIN_X = width / 2, ORIGIN_Y = height / 2;
      // Deterministic PRNG (mulberry32) so refreshing the page lays
      // the graph out identically. Seed is a hash of the sorted node
      // ids, so the same dataset always seeds the same way but a
      // different graph gets its own distinct pattern.
      let seed = 0x9e3779b9;
      const ids = nodes.map(n => n.id).sort();
      for (const id of ids) {
        for (let k = 0; k < id.length; k++) {
          seed = Math.imul(seed ^ id.charCodeAt(k), 0x85ebca6b);
          seed ^= seed >>> 13;
        }
      }
      const rand = () => {
        seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
        let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      };
      const jitter = (s) => (rand() * 2 - 1) * s;

      // 1. Seed entity positions from the pre-baked layout.
      //
      // The same JSON the entities-only view consumes
      // (data/entity-positions.json, generated by the offline baker)
      // provides x/y for every entity. Coordinates are roughly centred
      // on (0, 0); we translate by (width/2, height/2) and scale up by
      // ENTITY_LAYOUT_SCALE so there's extra room for the statement
      // cloud that anchors to each entity's position.
      //
      // Fallback for first paint (before the fetch resolves) or for
      // entities created since the last bake: place at canvas centre
      // with a tiny jitter; physics will float them outward and the
      // next baker run picks them up.
      const ENTITY_LAYOUT_SCALE = 1.6 * COMPACT_MULT;
      const entityIdx = nodes.filter(n => n.kind === 'entity');
      const baked = positionsRef.current && positionsRef.current.map;
      const entityPos = {};
      for (const e of entityIdx) {
        const p = baked ? baked[e.id] : null;
        if (p) {
          entityPos[e.id] = {
            x: ORIGIN_X + p.x * ENTITY_LAYOUT_SCALE,
            y: ORIGIN_Y + p.y * ENTITY_LAYOUT_SCALE,
          };
        } else {
          entityPos[e.id] = {
            x: ORIGIN_X + jitter(80),
            y: ORIGIN_Y + jitter(80),
          };
        }
      }

      // Centroid of all entities — fallback anchor for unmentioning
      // statements. If there are no entities at all (edge case), use
      // canvas center.
      let cgx = 0, cgy = 0;
      const placedPositions = Object.values(entityPos);
      if (placedPositions.length) {
        for (const p of placedPositions) { cgx += p.x; cgy += p.y; }
        cgx /= placedPositions.length; cgy /= placedPositions.length;
      } else {
        cgx = ORIGIN_X; cgy = ORIGIN_Y;
      }

      // 2 + 3. Place each node.
      const stmtById = {};
      for (const b of data.statements) stmtById[b.id] = b;
      // Pre-compute entity↔entity degree from the baked positions so we
      // can spawn each statement next to its *most-connected* mentioned
      // entity. The centroid approach (previous behaviour) put statements
      // with two far-apart mentions in dead space halfway between, so
      // they had to drift across the canvas before springs settled them.
      // Anchoring to a single specific entity puts the statement next
      // to something it's actually related to from frame 1.
      const entityDegreeMap = {};
      for (const e of entityIdx) entityDegreeMap[e.id] = 0;
      for (const ed of edges) {
        if (ed.kind !== 'entity') continue;
        if (entityDegreeMap[ed.source] !== undefined) entityDegreeMap[ed.source]++;
        if (entityDegreeMap[ed.target] !== undefined) entityDegreeMap[ed.target]++;
      }
      // Spawn jitter is ~2× the spring rest length (LINK_DIST is 160
      // below). Past the rest length means the spring force is
      // inward, so statements visibly drift toward their entity at
      // simulation start instead of appearing frozen at their final
      // position from frame 1 — the "settling in" motion is part of
      // the feel we want to preserve.
      const STMT_SPAWN_RADIUS = 320 * COMPACT_MULT;
      // Entities are heavy so statements get pulled toward them, not
      // the other way around. Each spring force on a node is divided
      // by its mass during integration (a = F/m), so an entity 25×
      // heavier than a statement accelerates 25× less under the same
      // pull. The asymmetry stabilizes entity positions and lets
      // statement clouds settle around them instead of dragging them.
      const ENTITY_MASS = 25;
      const STATEMENT_MASS = 1;
      const np = nodes.map(n => {
        if (n.kind === 'entity') {
          const p = entityPos[n.id];
          // fx/fy pins the entity at its baked position — the integrator
          // (see the `if (n.fx !== undefined)` branch below) honours this
          // by snapping x/y back to fx/fy every frame and zeroing velocity.
          // Statements still feel spring pulls toward this fixed point.
          return {
            ...n,
            x: p.x, y: p.y,
            fx: p.x, fy: p.y,
            vx: 0, vy: 0,
            degree: 0,
            invMass: 1 / ENTITY_MASS,
          };
        }
        // Statement: anchor next to the highest-degree mentioned entity.
        // The chosen entity is pinned (baked positions), so it's a
        // stable starting point. For multi-mention statements, the
        // springs from the other mentions then pull the statement
        // toward its equilibrium position between all of them — but it
        // always starts close to a real entity, not in dead space.
        const stmt = stmtById[n.id];
        const ents = stmt && stmt.mentions ? stmt.mentions.filter(eid => entityPos[eid]) : [];
        let ax, ay;
        if (ents.length) {
          const anchorId = ents.reduce(
            (best, eid) => (entityDegreeMap[eid] || 0) > (entityDegreeMap[best] || 0) ? eid : best,
            ents[0],
          );
          const ap = entityPos[anchorId];
          ax = ap.x; ay = ap.y;
        } else {
          // Orphan statement (no mentions) — drop it at the entity
          // centroid as before, since there's nothing better to anchor to.
          ax = cgx; ay = cgy;
        }
        return {
          ...n,
          x: ax + jitter(STMT_SPAWN_RADIUS),
          y: ay + jitter(STMT_SPAWN_RADIUS),
          vx: 0, vy: 0,
          degree: 0,
          invMass: 1 / STATEMENT_MASS,
        };
      });
      const idMap = {};
      np.forEach(n => idMap[n.id] = n);
      const ep = edges.map(e => ({ ...e, src: idMap[e.source], tgt: idMap[e.target] })).filter(e => e.src && e.tgt);
      // Precompute total node degree (for degree-weighted springs) and
      // each entity's entity↔entity degree (drives the force-field
      // radius below) plus its set of directly-connected entity ids
      // (force-field exclusions).
      for (const n of np) {
        n.entityDegree = 0;
        if (n.kind === 'entity') n.entityNeighbors = new Set();
      }
      for (const e of ep) {
        e.src.degree++; e.tgt.degree++;
        if (e.kind === 'entity') {
          if (e.src.kind === 'entity') {
            e.src.entityDegree++;
            e.src.entityNeighbors.add(e.tgt.id);
          }
          if (e.tgt.kind === 'entity') {
            e.tgt.entityDegree++;
            e.tgt.entityNeighbors.add(e.src.id);
          }
        }
      }
      // Cache the per-edge weight 1/sqrt(deg(src) * deg(tgt)) to avoid
      // recomputing each frame. Floor at 1 to avoid div-by-zero.
      for (const e of ep) {
        e.weight = 1 / Math.sqrt(Math.max(1, e.src.degree) * Math.max(1, e.tgt.degree));
      }
      // Cache entity-only list for the entity-entity repulsion pass.
      // Entities all settle near their mention centroid, which for many
      // entities is roughly the global center of the graph — so they
      // collapse into a central blob even when statements are well laid
      // out. A short-range mutual repulsion gives them personal space
      // without affecting how they're anchored relative to statements.
      // Scale the initial wake window with node count: the phyllotaxis
      // spawn starts close to equilibrium for repulsion, so motion is
      // gentle and the layout converges by springs alone — which is
      // slower for bigger graphs. A flat 2.5s was fine at ~1k nodes
      // but quenches too early at ~2k. Cap at 12s so it's never silly.
      const initialWakeMs = Math.min(12000, 2500 + np.length * 2);
      const entityNodes = np.filter(n => n.kind === 'entity');
      simRef.current = {
        nodes: np, edges: ep, idMap, entities: entityNodes,
        spreadScale,
        dragging: null, pan: {x:0,y:0}, zoom: 1, panning: null,
        // Quench state — when total kinetic energy drops below a small
        // threshold, the RAF loop pauses. Any user interaction (drag,
        // hover, pan, zoom, toolbar toggle) bumps `wakeUntil` so the
        // sim runs for a brief window even when the graph was settled.
        running: true, wakeUntil: performance.now() + initialWakeMs,
      };
      // Embedded view auto-fits the camera so curators land looking at
      // the content instead of an empty quadrant of the canvas. Fit
      // runs twice: a fast pass once the integrator has relaxed obvious
      // overlaps, then again after the wake window so the final layout
      // is correctly framed. Reads canvas dimensions fresh at fit time
      // (rather than the closure-captured values) because
      // ResizeObserver may not have fired by the first scheduled tick.
      if (embedded) {
        const fitNow = () => {
          const s = simRef.current;
          if (!s || !s.nodes.length) return;
          const w = container.clientWidth, h = container.clientHeight;
          if (w <= 0 || h <= 0) return;
          let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
          for (const n of s.nodes) {
            if (n.x < minX) minX = n.x;
            if (n.y < minY) minY = n.y;
            if (n.x > maxX) maxX = n.x;
            if (n.y > maxY) maxY = n.y;
          }
          const bw = Math.max(1, maxX - minX);
          const bh = Math.max(1, maxY - minY);
          const PAD = 60;
          const zX = (w - PAD * 2) / bw;
          const zY = (h - PAD * 2) / bh;
          const z = Math.max(0.3, Math.min(2.5, Math.min(zX, zY)));
          s.zoom = z;
          s.pan.x = w / 2 - ((minX + maxX) / 2) * z;
          s.pan.y = h / 2 - ((minY + maxY) / 2) * z;
        };
        // First fit: quick framing as soon as the spawn positions are
        // in. Second fit: after the wake window settles, snap to the
        // final layout. User interactions in between (drag/zoom) just
        // get overwritten — acceptable given they happen in the first
        // ~1.5s of a fresh page load.
        setTimeout(fitNow, 200);
        setTimeout(fitNow, Math.min(2000, initialWakeMs + 200));
      }
    }
    const sim = simRef.current;
    const wake = (ms = 600) => { sim.wakeUntil = performance.now() + ms; if (!sim.running) { sim.running = true; raf = requestAnimationFrame(step); } };

    // Mouse handling
    let mouse = { x: 0, y: 0, down: false };
    const screenToWorld = (sx, sy) => ({
      x: (sx - sim.pan.x) / sim.zoom,
      y: (sy - sim.pan.y) / sim.zoom,
    });

    const findNodeAt = (sx, sy) => {
      const w = screenToWorld(sx, sy);
      for (let i = sim.nodes.length - 1; i >= 0; i--) {
        const n = sim.nodes[i];
        const r = nodeRadius(n);
        if (Math.hypot(n.x - w.x, n.y - w.y) <= r + 4 / sim.zoom) return n;
      }
      return null;
    };

    // Hit-test the condition markers (drawn each frame at edge midpoints).
    // Generous radius so the marker is comfortable to click — the visible
    // disc is 5.5px but the hit area is ~10 to forgive imprecise clicks.
    // Returns the first leaf statement_id that lives in the marker's
    // when-tree; for composite AND/OR trees that's the first leaf, which
    // is the simplest "which underlying statement do I jump to" answer
    // and keeps clicking deterministic.
    const findCondHitAt = (sx, sy) => {
      if (!sim.condHits || !sim.condHits.length) return null;
      const w = screenToWorld(sx, sy);
      const tol = 10 / sim.zoom;
      for (let i = sim.condHits.length - 1; i >= 0; i--) {
        const h = sim.condHits[i];
        if (Math.hypot(h.x - w.x, h.y - w.y) <= tol) return h;
      }
      return null;
    };

    const onMouseDown = (e) => {
      const rect = canvas.getBoundingClientRect();
      mouse.x = e.clientX - rect.left;
      mouse.y = e.clientY - rect.top;
      mouse.down = true;
      const n = findNodeAt(mouse.x, mouse.y);
      if (n) {
        sim.dragging = n;
        n.fx = n.x; n.fy = n.y;
        wake(2000);  // a drag wants the sim live so neighbors react
        return;
      }
      const hit = findCondHitAt(mouse.x, mouse.y);
      if (hit) {
        // Defer the selection to mouseup so a drag-away cancels it,
        // matching node-click behavior. Stash the pending hit on sim
        // so onMouseUp can read it without re-running hit testing.
        sim.condClick = { x: mouse.x, y: mouse.y, leafId: hit.leafId };
        wake();
        return;
      }
      sim.panning = { startX: mouse.x, startY: mouse.y, panX: sim.pan.x, panY: sim.pan.y };
      wake();      // pan only needs the next paint, the layout itself isn't moving
    };
    const onMouseMove = (e) => {
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      mouse.x = sx; mouse.y = sy;
      if (sim.dragging) {
        const w = screenToWorld(sx, sy);
        sim.dragging.fx = w.x;
        sim.dragging.fy = w.y;
        wake(2000);
      } else if (sim.panning) {
        sim.pan.x = sim.panning.panX + (sx - sim.panning.startX);
        sim.pan.y = sim.panning.panY + (sy - sim.panning.startY);
        wake();
      } else {
        const n = findNodeAt(sx, sy);
        const cond = n ? null : findCondHitAt(sx, sy);
        const next = n ? n.id : null;
        setHoverId((prev) => next === prev ? prev : next);
        canvas.style.cursor = (n || cond) ? 'pointer' : 'grab';
        if (next || cond) wake(150);  // hover halo needs one repaint, not a full sim
      }
    };
    const onMouseUp = (e) => {
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const moved = sim.panning && (Math.abs(sx - sim.panning.startX) + Math.abs(sy - sim.panning.startY) > 4);
      const draggedFar = sim.dragging && (Math.hypot((sim.dragging.fx ?? sim.dragging.x) - sim.dragging.x, (sim.dragging.fy ?? sim.dragging.y) - sim.dragging.y) > 4);
      if (sim.dragging) {
        const draggedId = sim.dragging.id;
        if (!draggedFar) {
          // treat as click — toggle off if reclicking the same node,
          // otherwise select. Capture id locally; React may invoke this
          // updater after sim.dragging is cleared below.
          setSelectedId((prev) => prev === draggedId ? null : draggedId);
        }
        // Entities are permanently pinned to their baked (or
        // dragged-to) position; keep fx/fy so they stay there.
        // Statements were only temporarily pinned during the drag —
        // release them so physics resumes.
        if (sim.dragging.kind !== 'entity') {
          delete sim.dragging.fx;
          delete sim.dragging.fy;
        }
        sim.dragging = null;
      } else if (sim.condClick) {
        const dx = sx - sim.condClick.x;
        const dy = sy - sim.condClick.y;
        if (Math.hypot(dx, dy) <= 5) {
          const target = sim.condClick.leafId;
          setSelectedId((prev) => prev === target ? null : target);
        }
        sim.condClick = null;
      } else if (sim.panning && !moved) {
        // Background click — clear selection so the side panel returns
        // to the empty state.
        setSelectedId(null);
      }
      sim.panning = null;
      mouse.down = false;
    };
    const onDblClick = (e) => {
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const n = findNodeAt(sx, sy);
      if (n) {
        router.go({ view: n.kind, id: n.id });
      }
    };
    const onWheel = (e) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const factor = Math.exp(-e.deltaY * 0.0015);
      const newZoom = Math.max(0.3, Math.min(3, sim.zoom * factor));
      // zoom around cursor
      sim.pan.x = sx - (sx - sim.pan.x) * (newZoom / sim.zoom);
      sim.pan.y = sy - (sy - sim.pan.y) * (newZoom / sim.zoom);
      sim.zoom = newZoom;
      wake();
    };

    const onKeyDown = (e) => {
      if (e.key === 'Escape') setSelectedId(null);
    };

    canvas.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    canvas.addEventListener('dblclick', onDblClick);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    window.addEventListener('keydown', onKeyDown);

    // Read latest state via refs at draw time
    const stateRef = { selectedId, hoverId, neighborhood, activeTypes, showEntities, showStatements, theme: tweaks.theme, searchMatches };
    drawRef.current.state = stateRef;

    // Simulation loop. The repulsion uses a spatial grid so it's
    // ~O(N) instead of O(N²) — at 1000+ nodes the naive form burns
    // ~1.4M ops per frame and stutters. The loop also pauses itself
    // once the layout settles (low total kinetic energy and no recent
    // user interaction); wake() restarts it on demand.
    //
    // Force model: each frame accumulates ALL forces (repulsion +
    // gravity + springs) into per-node fx/fy buffers, then a single
    // pass damps, caps, and integrates. Springs run for every edge
    // regardless of the toolbar's activeTypes filter — that filter
    // controls only what's drawn. Otherwise hiding `mentions` would
    // strand entities with no spring forces, leaving them drifting
    // sluggishly while linked statements animated around them. The
    // per-node force cap (MAX_F) protects against any popular-hub
    // node being yanked too hard when many edges pull at once.
    let raf;
    // Repulsion strength. Bumped up so the inner-cluster pressure
    // can actually push back against the cumulative inward pull of
    // all the springs at once.
    const REPULSE = 2200;
    // Spring rest length — connected pairs settle this far apart.
    // Larger value spreads each cluster's footprint, which is what
    // ultimately decompresses the inner core.
    const LINK_DIST = 160 * (embedded ? 0.5 : 1);
    // Per-edge-type spring strength. Statement-link edges are the
    // structural skeleton (contains, triggers, enables, etc.).
    // Mentions are noisy by design — popular entities are referenced
    // by hundreds of statements — so they pull much more gently to
    // avoid the cumulative tug crushing the layout into a blob.
    const LINK_K_DEFAULT = 0.03;
    const LINK_K_MENTIONS = 0.01;
    // Degree-weighted springs: each spring's strength is divided by
    // sqrt(deg(src) * deg(tgt)). This is the load-bearing fix for
    // dense substrates — without it, a hub node with 100+ edges
    // accumulates 100× the inward pull of a leaf node and dominates
    // the layout. With it, hubs feel each spring proportionally
    // less hard, so they sit naturally in their cluster instead of
    // being yanked into the center under cumulative load.
    const DEGREE_WEIGHTING = true;
    // Center gravity, very weak. Just enough to keep disconnected
    // components from drifting off; not strong enough to compete
    // with springs for cluster placement.
    //
    // Lower than before because the entity-anchored seed already
    // distributes nodes across a wide canvas — we don't want gravity
    // slowly collapsing that spread back into a central blob over the
    // many seconds the simulation runs.
    // Scale inversely with spread so the equilibrium layout for large
    // graphs sits at the same fraction of canvas as for small ones —
    // otherwise gravity slowly squeezes a wide spawn back into a
    // tighter blob and the extra spread is lost.
    const CENTER_GRAVITY = 0.00015 / Math.max(1, sim.spreadScale || 1);
    // Per-entity "force field": each entity carves out a territory
    // proportional to the number of *other entities* it's directly
    // linked to. Nodes inside the field that aren't direct entity
    // neighbours are pushed outward; nodes that share an entity↔entity
    // edge with the field's owner pass through freely. Visually this
    // gives a hub-with-many-friends a generous breathing zone, while
    // a leaf entity has almost none — the topology shapes the layout.
    const FIELD_BASE_RADIUS = 140;       // every entity gets at least this
    const FIELD_RADIUS_PER_LINK = 32;    // grows linearly with entity-degree
    const FIELD_STRENGTH = 90;           // tuned against MAX_F (=40)
    // Cell size matters: too small and most pairs spill into multi-cell
    // checks; too large and the 3×3 neighborhood approaches O(N²) again.
    // 110 keeps each cell to a handful of nodes at typical link distance.
    const CELL = 110;
    // Nodes farther apart than this contribute negligibly to repulsion
    // anyway (~1/d²), so the spatial truncation is essentially exact.
    const REPULSE_CUTOFF_SQ = (CELL * 1.5) * (CELL * 1.5);
    const QUENCH_KE = 0.25;     // total KE per node below which we sleep
    const DAMPING = 0.78;
    const TIME_STEP = 0.05;
    // Caps tame transient spikes — per-node total force, then per-node
    // velocity. Without these, a high-degree node accumulates many
    // simultaneous spring forces and the integrator translates them
    // into hundreds-of-pixels jumps that look like flying.
    const MAX_F = 40;
    const MAX_F_SQ = MAX_F * MAX_F;
    // Velocity cap raised so satellites can traverse the wide canvas
    // to their hub in seconds instead of half a minute. With the
    // entity mass at 25, a sub-entity's acceleration is small but
    // its top speed was the real bottleneck — at MAX_V=60 it covered
    // 3 px/frame, ~180 px/sec.
    const MAX_V = 180;
    const MAX_V_SQ = MAX_V * MAX_V;

    const step = () => {
      const now = performance.now();
      const N = sim.nodes.length;
      const center = { x: width / 2, y: height / 2 };
      // Run 4 physics sub-steps per RAF frame. This keeps the layout
      // responsive to drags and data changes without making the
      // simulation feel sluggish — settling that would otherwise take
      // dozens of seconds completes in a few.
      const substeps = 4;
      let ke = 0;
      for (let sub = 0; sub < substeps; sub++) {
      ke = 0;

      // Bucket nodes into cells. A flat Map keyed by `gx*M+gy` is faster
      // than nested objects/maps in V8 for this size.
      const grid = new Map();
      for (const n of sim.nodes) {
        n.fxAcc = 0; n.fyAcc = 0;  // reset force accumulator
        const gx = Math.floor(n.x / CELL);
        const gy = Math.floor(n.y / CELL);
        const key = gx * 100000 + gy;
        let bucket = grid.get(key);
        if (!bucket) { bucket = []; grid.set(key, bucket); }
        bucket.push(n);
      }

      // Repulsion: only check the node's own cell + 8 neighbors.
      for (let i = 0; i < N; i++) {
        const a = sim.nodes[i];
        const gx = Math.floor(a.x / CELL);
        const gy = Math.floor(a.y / CELL);
        for (let dx = -1; dx <= 1; dx++) {
          for (let dy = -1; dy <= 1; dy++) {
            const bucket = grid.get((gx + dx) * 100000 + (gy + dy));
            if (!bucket) continue;
            for (const b of bucket) {
              if (a === b) continue;
              const ddx = a.x - b.x;
              const ddy = a.y - b.y;
              const d2 = ddx * ddx + ddy * ddy + 0.01;
              if (d2 > REPULSE_CUTOFF_SQ) continue;
              const d = Math.sqrt(d2);
              const f = REPULSE / d2;
              a.fxAcc += (ddx / d) * f;
              a.fyAcc += (ddy / d) * f;
            }
          }
        }
        // Gravity intentionally disabled: springs (and the spawn
        // layout) handle clustering; gravity only ever pulled
        // unconnected nodes blindly toward the canvas center, which
        // isn't where anything meaningful lives.
      }

      // Entity force fields — per entity, push every OTHER entity that
      // isn't a direct entity-link neighbour outside a radius scaled by
      // the entity's link count. Entities are ~hundreds, so the O(E²)
      // pass costs a few tens of thousands of ops per substep — well
      // within budget. Statements are deliberately exempt: the field
      // shapes the entity skeleton, the statement cloud follows via
      // mention springs without being shoved around.
      const ents = sim.entities;
      const Ec = ents.length;
      for (let i = 0; i < Ec; i++) {
        const a = ents[i];
        const aRadius = FIELD_BASE_RADIUS + a.entityDegree * FIELD_RADIUS_PER_LINK;
        const aR2 = aRadius * aRadius;
        for (let j = 0; j < Ec; j++) {
          if (i === j) continue;
          const b = ents[j];
          if (a.entityNeighbors && a.entityNeighbors.has(b.id)) continue;
          const ddx = b.x - a.x;
          const ddy = b.y - a.y;
          const d2 = ddx * ddx + ddy * ddy + 0.01;
          if (d2 > aR2) continue;
          const d = Math.sqrt(d2);
          // Linear ramp from full strength at the centre to zero at
          // the field boundary — smoother than 1/d² and avoids the
          // launch-on-overlap spikes a singular field would create.
          const f = FIELD_STRENGTH * (1 - d / aRadius);
          b.fxAcc += (ddx / d) * f;
          b.fyAcc += (ddy / d) * f;
        }
      }

      // Spring forces — every edge contributes regardless of the
      // toolbar's link-type filter (that's display-only).
      //
      // Statement→entity (mention) springs are asymmetric: only the
      // statement is pulled. The entity skeleton is shaped by the
      // entity-link graph and the force field, not by the statement
      // cloud — so a statement that mentions an entity gravitates to
      // it, but doesn't tug the entity back. This is what the user
      // means by "statements can't pull entities around."
      //
      // Statement↔statement and entity↔entity springs remain
      // symmetric. Degree-weighting still applies to statement↔
      // statement to keep hub statements from being yanked.
      for (const e of sim.edges) {
        const dx = e.tgt.x - e.src.x;
        const dy = e.tgt.y - e.src.y;
        const d = Math.hypot(dx, dy) + 0.01;
        const k = e.link_type === 'mentions' ? LINK_K_MENTIONS : LINK_K_DEFAULT;
        const w = (DEGREE_WEIGHTING && e.kind !== 'entity') ? e.weight : 1;
        const f = (d - LINK_DIST) * k * w;
        const fx = (dx / d) * f;
        const fy = (dy / d) * f;
        if (e.kind === 'mention') {
          // src is the statement, tgt is the entity. Pull only the
          // statement — entities stay put under mention springs.
          e.src.fxAcc += fx; e.src.fyAcc += fy;
        } else {
          e.src.fxAcc += fx; e.src.fyAcc += fy;
          e.tgt.fxAcc -= fx; e.tgt.fyAcc -= fy;
        }
      }

      // Damp + cap + integrate in one pass.
      for (const n of sim.nodes) {
        if (n.fx !== undefined) {
          n.x = n.fx; n.y = n.fy; n.vx = 0; n.vy = 0;
          continue;
        }
        // Per-node force cap: keeps high-degree nodes (entities with
        // hundreds of mentions) from being yanked across the canvas
        // when many springs pull at once.
        const fmag2 = n.fxAcc * n.fxAcc + n.fyAcc * n.fyAcc;
        if (fmag2 > MAX_F_SQ) {
          const scale = MAX_F / Math.sqrt(fmag2);
          n.fxAcc *= scale;
          n.fyAcc *= scale;
        }
        const inv = n.invMass !== undefined ? n.invMass : 1;
        n.vx = (n.vx + n.fxAcc * inv) * DAMPING;
        n.vy = (n.vy + n.fyAcc * inv) * DAMPING;
        // Velocity cap: belt-and-braces against any remaining edge case.
        const vmag2pre = n.vx * n.vx + n.vy * n.vy;
        if (vmag2pre > MAX_V_SQ) {
          const scale = MAX_V / Math.sqrt(vmag2pre);
          n.vx *= scale;
          n.vy *= scale;
        }
        n.x += n.vx * TIME_STEP;
        n.y += n.vy * TIME_STEP;
        ke += n.vx * n.vx + n.vy * n.vy;
      }
      }  // end substep loop

      draw();

      // Quench: stop the RAF loop if both (a) the layout has settled
      // and (b) no user interaction has bumped wakeUntil into the
      // future. Anything that wants the loop running calls wake().
      const settled = ke < QUENCH_KE * N;
      if (settled && now > sim.wakeUntil) {
        sim.running = false;
        return;  // do NOT requestAnimationFrame
      }
      raf = requestAnimationFrame(step);
    };

    function nodeRadius(n) {
      if (n.kind === 'statement') return 6;
      // entity bigger if more mentions
      const mentions = (idx.mentionsByEntity[n.id] || []).length;
      return 5 + Math.min(mentions, 6) * 1.4;
    }

    function draw() {
      const s = drawRef.current.state || stateRef;
      ctx.clearRect(0, 0, width, height);

      // Background subtle dot grid
      ctx.save();
      ctx.translate(sim.pan.x, sim.pan.y);
      ctx.scale(sim.zoom, sim.zoom);

      const colors = s.theme === 'dark' ? LINK_TYPE_COLORS_DARK : LINK_TYPE_COLORS_LIGHT;
      const edgeAlpha = s.theme === 'dark' ? 0.5 : 0.55;
      const dimAlpha = 0.08;
      const bgColor = s.theme === 'dark' ? '#0a0a0c' : '#ffffff';
      const fgColor = s.theme === 'dark' ? '#f4f4f5' : '#18181b';

      // Precompute the node-id sets that count as "incident to" the
      // current selection, hover, and search matches. Doing this once
      // per frame turns the per-node dim check from O(E) into O(1)
      // lookups.
      const selNeighbors = new Set();
      const hovNeighbors = new Set();
      const searchNeighbors = new Set();
      const searchActive = s.searchMatches && s.searchMatches.size > 0;
      if (s.selectedId || s.hoverId || searchActive) {
        for (const e of sim.edges) {
          if (s.selectedId) {
            if (e.source === s.selectedId) selNeighbors.add(e.target);
            else if (e.target === s.selectedId) selNeighbors.add(e.source);
          }
          if (s.hoverId) {
            if (e.source === s.hoverId) hovNeighbors.add(e.target);
            else if (e.target === s.hoverId) hovNeighbors.add(e.source);
          }
          if (searchActive) {
            // Treat each match like a clicked node — its direct
            // neighbors stay in focus too, so the user can read
            // structure around the match without losing context.
            if (s.searchMatches.has(e.source)) searchNeighbors.add(e.target);
            if (s.searchMatches.has(e.target)) searchNeighbors.add(e.source);
          }
        }
      }

      // Edges
      for (const e of sim.edges) {
        if (!s.activeTypes.has(e.link_type)) continue;
        const inHood = !s.neighborhood || (s.neighborhood.has(e.source) && s.neighborhood.has(e.target));
        const incidentToSel = s.selectedId && (e.source === s.selectedId || e.target === s.selectedId);
        const incidentToHover = s.hoverId && (e.source === s.hoverId || e.target === s.hoverId);
        // Search dimming mirrors selection dimming: an edge stays full
        // opacity if it's incident to ANY match, dim otherwise. Same
        // rule as "click a node, see its neighborhood."
        const incidentToMatch = searchActive && (s.searchMatches.has(e.source) || s.searchMatches.has(e.target));
        const anyFocus = s.selectedId || s.hoverId || searchActive;
        const dim = anyFocus ? !(incidentToSel || incidentToHover || incidentToMatch) : false;

        if (s.neighborhood && !inHood) continue;

        ctx.strokeStyle = colors[e.link_type] || '#888';
        ctx.globalAlpha = dim ? dimAlpha : edgeAlpha;
        // Entity↔entity edges are structural; render them thicker so
        // they read above the statement-link cloud. Mentions stay
        // dashed and thin to keep them low in the visual hierarchy.
        const isEntityEdge = e.kind === 'entity';
        const baseWidth = isEntityEdge ? 1.8 : 1;
        ctx.lineWidth = (incidentToSel || incidentToHover) ? baseWidth + 0.6 : baseWidth;
        if (e.link_type === 'mentions') {
          ctx.setLineDash([3, 3]);
        } else {
          ctx.setLineDash([]);
        }
        ctx.beginPath();
        ctx.moveTo(e.src.x, e.src.y);
        ctx.lineTo(e.tgt.x, e.tgt.y);
        ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;

      // Condition markers — for any edge with a `when` clause, draw a
      // bright amber disc at the edge midpoint plus a thin connector
      // back to each leaf condition node. The disc has to be visible
      // even when the user isn't looking for it: previous styling used
      // a 1.6px grey dot which blended into the edge cloud, making
      // conditional and unconditional edges indistinguishable at a
      // glance. Amber matches the capability tint and is reserved for
      // "this needs your attention" markers in the graph.
      const condMain = s.theme === 'dark' ? '#fbbf24' : '#d97706';
      const condFaint = s.theme === 'dark' ? '#92400e' : '#fde68a';
      // Reset and rebuild the click hit-list every frame; positions
      // change with the simulation. `leafId` is the first leaf of the
      // when-tree so a click jumps to a deterministic underlying
      // statement node.
      sim.condHits = [];
      ctx.save();
      for (const e of sim.edges) {
        if (e.kind !== 'statement' || !e.when) continue;
        if (s.neighborhood && (!s.neighborhood.has(e.src.id) && !s.neighborhood.has(e.tgt.id))) continue;
        const mx = (e.src.x + e.tgt.x) / 2;
        const my = (e.src.y + e.tgt.y) / 2;
        // Only record the hit if the marker is actually visible (not
        // dimmed-out by a selection that excludes both endpoints).
        let firstLeaf = null;
        for (const lid of walkWhenLeavesG(e.when)) { firstLeaf = lid; break; }
        if (firstLeaf && sim.idMap[firstLeaf]) {
          sim.condHits.push({ x: mx, y: my, leafId: firstLeaf });
        }

        // Match the dim treatment used by the edges themselves: when
        // any focus state is active (selection / hover / search), edges
        // not incident to the focus fade to dimAlpha. Markers attach
        // to those edges so they must dim in lockstep.
        const incidentToSel = s.selectedId && (e.source === s.selectedId || e.target === s.selectedId);
        const incidentToHover = s.hoverId && (e.source === s.hoverId || e.target === s.hoverId);
        const searchActiveCond = s.searchMatches && s.searchMatches.size > 0;
        const incidentToMatch = searchActiveCond && (s.searchMatches.has(e.source) || s.searchMatches.has(e.target));
        const anyFocusCond = s.selectedId || s.hoverId || searchActiveCond;
        const dim = anyFocusCond ? !(incidentToSel || incidentToHover || incidentToMatch) : false;
        const baseAlpha = dim ? dimAlpha : 1;

        // Connector lines from each leaf condition node to the midpoint.
        ctx.strokeStyle = condMain;
        ctx.lineWidth = 0.8;
        ctx.setLineDash([2, 3]);
        ctx.globalAlpha = 0.55 * baseAlpha;
        for (const leafId of walkWhenLeavesG(e.when)) {
          const cn = sim.idMap[leafId];
          if (!cn) continue;
          if (s.neighborhood && !s.neighborhood.has(cn.id)) continue;
          ctx.beginPath();
          ctx.moveTo(cn.x, cn.y);
          ctx.lineTo(mx, my);
          ctx.stroke();
        }
        ctx.setLineDash([]);

        // Midpoint disc — the unmissable marker. Slight halo so it
        // reads against any edge color.
        ctx.globalAlpha = 0.85 * baseAlpha;
        ctx.fillStyle = condFaint;
        ctx.beginPath();
        ctx.arc(mx, my, 5.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1 * baseAlpha;
        ctx.fillStyle = condMain;
        ctx.beginPath();
        ctx.arc(mx, my, 3.2, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = bgColor;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      ctx.restore();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;

      // Nodes
      for (const n of sim.nodes) {
        if (n.kind === 'entity' && !s.showEntities) continue;
        if (n.kind === 'statement' && !s.showStatements) continue;
        if (s.neighborhood && !s.neighborhood.has(n.id)) continue;

        const isSel = n.id === s.selectedId;
        const isHov = n.id === s.hoverId;
        const isMatch = searchActive && s.searchMatches.has(n.id);
        // Same dim rule as a clicked node: full opacity if you're a
        // match, a selection, a hover, or a direct neighbor of any of
        // those. Otherwise dim. This makes a search visually identical
        // to "many things selected at once."
        const anyFocusNode = s.selectedId || s.hoverId || searchActive;
        const isFocusOrNeighbor = isSel || isHov || isMatch ||
          (s.selectedId && selNeighbors.has(n.id)) ||
          (s.hoverId && hovNeighbors.has(n.id)) ||
          (searchActive && searchNeighbors.has(n.id));
        const dim = anyFocusNode && !isFocusOrNeighbor;

        // Condition-bearing statements (referenced as a `when` leaf
        // somewhere) render demoted: smaller and more transparent. They
        // still exist as nodes — navigable, can have their own children
        // — but visually read as edge metadata, not peers of the events.
        const isCondition = n.kind === 'statement' && (idx.conditionUses[n.id] || []).length > 0;
        const sizeMult = (isSel ? 1.4 : isHov ? 1.2 : 1) * (isCondition && !isSel && !isHov ? 0.65 : 1);
        ctx.globalAlpha = dim ? 0.25 : (isCondition && !isSel && !isHov ? 0.7 : 1);
        const r = nodeRadius(n) * sizeMult;

        if (n.kind === 'statement') {
          // Per-claim-kind palette. Condition-only nodes always render
          // muted (they read as edge metadata, not peers). Otherwise:
          // events = violet, states = teal, capabilities = amber. Open
          // vocabulary; unknown kinds fall through to violet.
          const claimColors = s.theme === 'dark'
            ? { event: '#c4b5fd', state: '#5eead4', capability: '#fcd34d' }
            : { event: '#7c3aed', state: '#0d9488', capability: '#b45309' };
          ctx.fillStyle = isCondition
            ? (s.theme === 'dark' ? '#94a3b8' : '#64748b')
            : (claimColors[n.claimKind] || claimColors.event);
          ctx.strokeStyle = bgColor;
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
        } else {
          ctx.fillStyle = s.theme === 'dark' ? '#22d3ee' : '#0e7490';
          ctx.strokeStyle = bgColor;
          ctx.lineWidth = 2;
          ctx.save();
          ctx.translate(n.x, n.y);
          ctx.rotate(Math.PI / 4);
          ctx.beginPath();
          ctx.rect(-r, -r, r * 2, r * 2);
          ctx.fill();
          ctx.stroke();
          ctx.restore();
        }

        if (isSel || isHov || isMatch) {
          // Same blue halo for clicks, hovers, and search matches —
          // search hits read as "selected" rather than as a separate
          // visual category.
          ctx.strokeStyle = s.theme === 'dark' ? '#60a5fa' : '#2563eb';
          ctx.lineWidth = 1.4;
          ctx.beginPath();
          ctx.arc(n.x, n.y, r + 5, 0, Math.PI * 2);
          ctx.stroke();
        }

        // Label
        const showLabel = isSel || isHov || isMatch || sim.zoom > 1.1 || n.kind === 'entity';
        if (showLabel) {
          const label = n.label.length > 36 ? n.label.slice(0, 33) + '…' : n.label;
          ctx.font = `${(isSel || isHov) ? '600 ' : '500 '}${11 / Math.max(1, sim.zoom * 0.9)}px Inter, sans-serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';
          ctx.lineWidth = 3 / sim.zoom;
          ctx.strokeStyle = bgColor;
          ctx.strokeText(label, n.x, n.y + r + 4);
          ctx.fillStyle = fgColor;
          ctx.fillText(label, n.x, n.y + r + 4);
        }
        ctx.globalAlpha = 1;
      }

      ctx.restore();
    }

    drawRef.current.draw = draw;
    drawRef.current.requestStep = () => {
      if (!sim.running) {
        sim.running = true;
        raf = requestAnimationFrame(step);
      }
    };
    raf = requestAnimationFrame(step);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      canvas.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      canvas.removeEventListener('dblclick', onDblClick);
      canvas.removeEventListener('wheel', onWheel);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [nodes, edges, positionsTick]);

  // Refs for state synced into draw
  const drawRef = useRefG({});
  useEffectG(() => {
    drawRef.current.state = { selectedId, hoverId, neighborhood, activeTypes, showEntities, showStatements, theme: tweaks.theme, searchMatches };
    // Any visual state change needs at least one repaint — even if the
    // sim is quenched, we owe the user a frame so the toggle is visible.
    const sim = simRef.current;
    if (sim) {
      sim.wakeUntil = performance.now() + 200;
      if (!sim.running && drawRef.current.requestStep) drawRef.current.requestStep();
    }
  }, [selectedId, hoverId, neighborhood, activeTypes, showEntities, showStatements, tweaks.theme, searchMatches]);

  // Update focus ID from prop
  useEffectG(() => { if (focusId) setSelectedId(focusId); }, [focusId]);

  const colors = tweaks.theme === 'dark' ? LINK_TYPE_COLORS_DARK : LINK_TYPE_COLORS_LIGHT;
  // Filter list is driven by the data: every link_type that actually
  // appears on a statement_link or entity_link edge, plus the synthetic
  // statement→entity edge types (one per registered claim kind) so the
  // user can toggle those on/off too. Sorted alphabetically. Types
  // without a registered color fall through to a neutral grey via the
  // `colors[t] || '#888'` pattern already used by the renderer.
  const { allTypes, typeCounts } = useMemoG(() => {
    const counts = {};
    data.links.forEach(l => { counts[l.link_type] = (counts[l.link_type] || 0) + 1; });
    (data.entity_links || []).forEach(l => { counts[l.link_type] = (counts[l.link_type] || 0) + 1; });
    // Statement→entity edges are synthesized from each statement's
    // `mentions` array; their type is derived from the statement's claim
    // kind via `stmtEntityEdgeType` (state→describes, capability→applies-
    // to, event→involves, anything else→mentions). Count them here so
    // the toolbar can toggle and show their volume.
    data.statements.forEach(b => {
      const t = stmtEntityEdgeType(b.kind);
      const m = (b.mentions || []).length;
      counts[t] = (counts[t] || 0) + m;
    });
    KNOWN_STMT_ENTITY_TYPES.forEach(t => { if (!(t in counts)) counts[t] = 0; });
    // Always expose `mentions` as a filter row — it's the catch-all
    // statement→entity edge type for any claim kind we haven't given a
    // dedicated edge type yet, and the user should be able to toggle it
    // even when no current claim kind happens to fall through to it.
    if (!('mentions' in counts)) counts['mentions'] = 0;
    return { allTypes: Object.keys(counts).sort(), typeCounts: counts };
  }, [data]);
  const fallbackSwatch = tweaks.theme === 'dark' ? '#6b6b73' : '#a1a1aa';

  const selected = selectedId ? idx.byId[selectedId] : null;
  const selectedNeighbors = selected ? (() => {
    const out = [];
    if (selected.kind === 'statement') {
      (idx.outgoing[selected.id] || []).forEach(l => out.push({ dir: 'out', link_type: l.link_type, target: idx.byId[l.to] }));
      (idx.incoming[selected.id] || []).forEach(l => out.push({ dir: 'in', link_type: l.link_type, target: idx.byId[l.from] }));
      const selfType = stmtEntityEdgeType(selected.claimKind);
      (selected.mentions || []).forEach(eid => out.push({ dir: 'out', link_type: selfType, target: idx.byId[eid] }));
    } else if (selected.kind === 'entity') {
      (idx.mentionsByEntity[selected.id] || []).forEach(b => {
        out.push({ dir: 'in', link_type: stmtEntityEdgeType(b.kind), target: b });
      });
    }
    return out.filter(x => x.target);
  })() : [];

  return (
    <div className={`graph-page${embedded ? ' is-embedded' : ''}`}>
      <div className="graph-canvas-wrap" ref={containerRef}>
        <canvas ref={canvasRef} className="graph-canvas" />

        <div className="graph-search">
          <input
            type="text"
            className="graph-search-input"
            placeholder="search nodes…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            spellCheck={false}
          />
          {searchQuery && (
            <span className="graph-search-meta">
              {searchMatches ? `${searchMatches.size} match${searchMatches.size === 1 ? '' : 'es'}` : ''}
              <button
                type="button"
                className="graph-search-clear"
                onClick={() => setSearchQuery('')}
                title="clear search"
              >×</button>
            </span>
          )}
        </div>

        <div className="graph-toolbar">
          <button className={`graph-pill${focusMode ? '' : ' is-off'}`} onClick={() => setFocusMode(v => !v)}>
            <span className="swatch" style={{background: 'currentColor'}} />
            {focusMode ? 'focus mode · on' : 'focus mode · off'}
          </button>
          <button className={`graph-pill${showStatements ? '' : ' is-off'}`} onClick={() => setShowStatements(v => !v)}>
            <span className="swatch" style={{background: tweaks.theme === 'dark' ? '#c4b5fd' : '#7c3aed', borderRadius:'50%'}} />
            statements · {data.statements.length}
          </button>
          <button className={`graph-pill${showEntities ? '' : ' is-off'}`} onClick={() => setShowEntities(v => !v)}>
            <span className="swatch" style={{background: tweaks.theme === 'dark' ? '#22d3ee' : '#0e7490', transform:'rotate(45deg)'}} />
            entities · {data.entities.length}
          </button>
          {allTypes.map(t => {
            const on = activeTypes.has(t);
            const swatchColor = colors[t] || fallbackSwatch;
            const count = typeCounts[t] || 0;
            return (
              <button
                key={t}
                className={`graph-pill${on ? '' : ' is-off'}`}
                onClick={() => {
                  setActiveTypes(prev => {
                    const s = new Set(prev);
                    s.has(t) ? s.delete(t) : s.add(t);
                    return s;
                  });
                }}
                title={count === 0 ? `${t} · no edges yet` : `${t} · ${count} edge${count === 1 ? '' : 's'}`}
              >
                <span className="swatch" style={{background: swatchColor, borderRadius: t === 'mentions' ? 4 : 2, height: t === 'mentions' ? 2 : 8}} />
                {t}
                {count > 0 && <span style={{marginLeft: 6, color: 'var(--ink-4)', fontSize: 10.5}}>{count.toLocaleString()}</span>}
              </button>
            );
          })}
        </div>

        <div className="graph-help">
          <span><b>drag</b> nodes · <b>scroll</b> zoom · <b>click</b> select · <b>double-click</b> open</span>
        </div>
      </div>

      {!embedded && <aside className="graph-side">
        {!selected && (
          <div>
            <h3>Graph</h3>
            <div className="graph-empty-state">
              The substrate has no root. Click any node to select it; double-click to open its detail view. Toggle a link type in the toolbar to fade it out.
            </div>
          </div>
        )}

        {selected && (
          <>
            <div>
              <div style={{display:'flex', gap:6, alignItems:'center', flexWrap:'wrap'}}>
                <KindTag kind={selected.kind} />
                {selected.kind === 'statement' && selected.claimKind && (
                  <ClaimKindTag kind={selected.claimKind} />
                )}
              </div>
              <div className="graph-focus-title" style={{marginTop:8}}>
                {selected.kind === 'entity' ? selected.name : selected.title}
              </div>
              <div style={{fontFamily:'var(--mono)', fontSize:10.5, color:'var(--ink-4)', marginTop:4}}>{selected.id}</div>

              {selected.kind === 'statement' && (
                <p style={{fontSize:13, color:'var(--ink-2)', marginTop:10, lineHeight:1.55}}>
                  {selected.text}
                </p>
              )}
              {selected.kind === 'entity' && (
                <p style={{fontSize:13, color:'var(--ink-2)', marginTop:10, lineHeight:1.55}}>
                  {selected.description}
                </p>
              )}

              <div style={{marginTop:18, display:'flex', gap:10}}>
                <button
                  className="graph-pill"
                  onClick={() => router.go({ view: selected.kind, id: selected.id })}
                  style={{color:'var(--accent)', borderColor:'var(--accent)'}}
                >
                  open detail →
                </button>
              </div>
            </div>

            <div>
              <h3>Neighborhood · {selectedNeighbors.length}</h3>
              <div style={{display:'flex', flexDirection:'column', gap:6}}>
                {selectedNeighbors.length === 0 && (
                  <div className="graph-empty-state">An island. Nothing connects to or from this node yet.</div>
                )}
                {selectedNeighbors.map((n, i) => (
                  <div
                    key={i}
                    onClick={() => setSelectedId(n.target.id)}
                    style={{
                      display:'grid',
                      gridTemplateColumns:'auto 1fr',
                      gap:10,
                      padding:'8px 0',
                      borderBottom:'1px dashed var(--rule)',
                      cursor:'pointer',
                      alignItems:'baseline',
                    }}
                  >
                    <span className={`linktype-tag lt-${n.link_type}`} style={{whiteSpace:'nowrap'}}>
                      {n.dir === 'out' ? '↗ ' : '↙ '}{n.link_type}
                    </span>
                    <span style={{fontSize:12.5, color:'var(--ink)', lineHeight:1.4}}>
                      {n.target.kind === 'entity' ? n.target.name : (n.target.title || n.target.text?.slice(0, 80))}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </aside>}
    </div>
  );
}

Object.assign(window, { GraphView });
