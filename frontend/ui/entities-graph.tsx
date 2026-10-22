// Entities-only force-directed graph view.
//
// Sister of GraphView, scoped to the entity layer: only entities are
// drawn, only entity↔entity links materialise as edges. No statements,
// no mention edges. Entity counts in practice are ~10² rather than
// ~10³, so the simulation can stay simple — naive O(N²) repulsion is
// fine, no spatial grid required.

const { useState: useStateE, useEffect: useEffectE, useRef: useRefE, useMemo: useMemoE } = React;

// Stable palette: type-name → palette index via a small djb2-style
// hash. Open vocabulary in, deterministic-but-distinct colors out.
const ENTITY_LINK_PALETTE_LIGHT = [
  '#6b3a8c', '#b14b1f', '#2f6b51', '#7c2f2a', '#4a5d8a',
  '#6e5a1c', '#355e3b', '#5a4a3a', '#1f6b6b', '#8c5a3a',
];
const ENTITY_LINK_PALETTE_DARK = [
  '#c9a8e0', '#e8a385', '#93c19d', '#d99183', '#98abd1',
  '#d4ba6e', '#9bb89f', '#c9bca0', '#7fc7c7', '#cfa787',
];
function entityLinkColor(type, theme) {
  const palette = theme === 'dark' ? ENTITY_LINK_PALETTE_DARK : ENTITY_LINK_PALETTE_LIGHT;
  if (!type) return palette[0];
  let h = 0;
  for (let i = 0; i < type.length; i++) h = (h * 31 + type.charCodeAt(i)) | 0;
  return palette[Math.abs(h) % palette.length];
}

// Inline form for adding a directed entity↔entity link from the
// currently-selected entity. Resolves the target by primary name —
// the datalist is populated with all entities so it offers
// autocomplete, but a free-typed name that doesn't match any entity
// is rejected on submit (we never auto-create entities here; that's a
// statement-authoring concern handled elsewhere).
function EntityLinkAddForm({ self, entities, knownTypes, onCreated, onCancel }) {
  const [direction, setDirection] = useStateE('out');
  const [targetText, setTargetText] = useStateE('');
  const [linkType, setLinkType] = useStateE('');
  const [busy, setBusy] = useStateE(false);
  const [err, setErr] = useStateE(null);

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    const t = targetText.trim();
    const lt = linkType.trim();
    if (!t) { setErr('target entity is required'); return; }
    if (!lt) { setErr('link type is required'); return; }
    const target = entities.find(en => en.name.toLowerCase() === t.toLowerCase());
    if (!target) { setErr(`unknown entity: ${t}`); return; }
    if (target.id === self.id) { setErr('cannot link an entity to itself'); return; }
    const from_entity_id = direction === 'out' ? self.id : target.id;
    const to_entity_id = direction === 'out' ? target.id : self.id;
    setBusy(true);
    try {
      await postJSON('/add-entity-links', {
        links: [{ from_entity_id, to_entity_id, link_type: lt }],
      });
      await onCreated();
    } catch (e) {
      setErr(e.message || String(e));
      setBusy(false);
      return;
    }
    setBusy(false);
  };

  return (
    <form onSubmit={submit} className="ent-edit-form">
      <div className="ent-edit-row">
        <label>direction</label>
        <select value={direction} onChange={e => setDirection(e.target.value)} disabled={busy}>
          <option value="out">{self.name} → target</option>
          <option value="in">target → {self.name}</option>
        </select>
      </div>
      <div className="ent-edit-row">
        <label>target</label>
        <input
          type="text"
          list="ent-edit-target-list"
          value={targetText}
          onChange={e => setTargetText(e.target.value)}
          placeholder="entity name"
          autoFocus
          disabled={busy}
          spellCheck={false}
        />
        <datalist id="ent-edit-target-list">
          {entities.map(en => (
            <option key={en.id} value={en.name} />
          ))}
        </datalist>
      </div>
      <div className="ent-edit-row">
        <label>type</label>
        <input
          type="text"
          list="ent-edit-type-list"
          value={linkType}
          onChange={e => setLinkType(e.target.value)}
          placeholder="contains, classifies, …"
          disabled={busy}
          spellCheck={false}
        />
        <datalist id="ent-edit-type-list">
          {knownTypes.map(t => (
            <option key={t} value={t} />
          ))}
        </datalist>
      </div>
      {err && <div className="ent-edit-error">{err}</div>}
      <div className="ent-edit-actions">
        <button type="button" className="graph-pill" onClick={onCancel} disabled={busy}>cancel</button>
        <button type="submit" className="graph-pill is-primary" disabled={busy}>
          {busy ? 'creating…' : 'create link'}
        </button>
      </div>
    </form>
  );
}

function EntitiesGraph({ focusId }) {
  const router = useRouter();
  const { tweaks, setTweak } = React.useContext(TweaksCtx);
  // Reading `version` makes the whole component re-render after a UI
  // mutation refetches /api/data — the actual substrate is held in
  // window globals and re-read on each render.
  const { version } = useDataCtx();
  const data = window.MYCELIUM_DATA;
  const idx = window.MYCELIUM_INDEX;
  const editMode = !!tweaks.showEditAffordances;
  const [searchQuery, setSearchQuery] = useStateE('');

  const canvasRef = useRefE(null);
  const containerRef = useRefE(null);
  const [hoverId, setHoverId] = useStateE(null);
  const [selectedId, setSelectedId] = useStateE(focusId || null);
  const [focusMode, setFocusMode] = useStateE(false);
  // Islands mode — when on, the highlight/jump system focuses on
  // entities that are NOT part of the biggest connected component.
  // A full transitive component analysis subsumes the user's "two or
  // three taps should be enough" rule, since any depth of indirect
  // connection (a chain of orphans connected only to each other) is
  // still cut off from the main component and so still flagged.
  const [showIslands, setShowIslands] = useStateE(false);

  const { allEntityLinkTypes, entityLinkTypeCounts } = useMemoE(() => {
    const counts = {};
    (data.entity_links || []).forEach(l => {
      counts[l.link_type] = (counts[l.link_type] || 0) + 1;
    });
    return {
      allEntityLinkTypes: Object.keys(counts).sort(),
      entityLinkTypeCounts: counts,
    };
  }, [data, version]);

  const [activeTypes, setActiveTypes] = useStateE(() => new Set(allEntityLinkTypes));

  // Islands set — entity ids that are NOT in the biggest connected
  // component of the entity↔entity graph. A solo entity, a pair, or
  // a five-entity chain that doesn't reach the main component all
  // qualify; only the entities in the largest cluster don't. Computed
  // once per data refresh so flipping the toggle is instant.
  const islandIds = useMemoE(() => {
    const adj = {};
    for (const e of data.entities) adj[e.id] = new Set();
    for (const l of data.entity_links || []) {
      if (adj[l.from] && adj[l.to]) {
        adj[l.from].add(l.to);
        adj[l.to].add(l.from);
      }
    }
    const visited = new Set();
    const components = [];
    for (const e of data.entities) {
      if (visited.has(e.id)) continue;
      const comp = [];
      const stack = [e.id];
      while (stack.length) {
        const id = stack.pop();
        if (visited.has(id)) continue;
        visited.add(id);
        comp.push(id);
        for (const nb of adj[id]) if (!visited.has(nb)) stack.push(nb);
      }
      components.push(comp);
    }
    components.sort((a, b) => b.length - a.length);
    const mainComponent = new Set(components[0] || []);
    const out = new Set();
    for (const e of data.entities) {
      if (!mainComponent.has(e.id)) out.add(e.id);
    }
    return out;
  }, [data, version]);

  // Highlight set — driven by either the search query or the islands
  // toggle. Islands mode wins when both are active so the user can
  // flip into the diagnostic without first clearing their search.
  // Aliases come from `idx.namesByEntity`, so a search for "sign-in"
  // matches an entity whose canonical name is "Login" if "sign-in" is
  // recorded as an alias.
  const matchSet = useMemoE(() => {
    if (showIslands) return islandIds.size > 0 ? islandIds : null;
    const q = searchQuery.trim().toLowerCase();
    if (!q) return null;
    const out = new Set();
    for (const e of data.entities) {
      if (e.name.toLowerCase().includes(q)) { out.add(e.id); continue; }
      const aliases = idx.namesByEntity[e.id] || [];
      if (aliases.some(n => n.text.toLowerCase().includes(q))) out.add(e.id);
    }
    return out;
  }, [searchQuery, data, idx, version, showIslands, islandIds]);
  // Keep filter set fresh: a brand-new type added through the editor
  // should be visible by default, not silently filtered out.
  useEffectE(() => {
    setActiveTypes(prev => {
      const next = new Set(prev);
      let changed = false;
      for (const t of allEntityLinkTypes) {
        if (!next.has(t)) { next.add(t); changed = true; }
      }
      return changed ? next : prev;
    });
  }, [allEntityLinkTypes]);

  // Nodes & edges — entity-only.
  const { nodes, edges } = useMemoE(() => {
    const nodes = data.entities.map(e => ({
      id: e.id, label: e.name, mentions: (idx.mentionsByEntity[e.id] || []).length,
    }));
    const edges = (data.entity_links || []).map(l => ({
      source: l.from, target: l.to, link_type: l.link_type,
    }));
    return { nodes, edges };
  }, [data, idx, version]);

  // Focus neighborhood
  const neighborhood = useMemoE(() => {
    if (!focusMode || !selectedId) return null;
    const set = new Set([selectedId]);
    edges.forEach(e => {
      if (e.source === selectedId) set.add(e.target);
      if (e.target === selectedId) set.add(e.source);
    });
    return set;
  }, [focusMode, selectedId, edges]);

  const simRef = useRefE(null);
  const drawRef = useRefE({});

  // Pre-baked positions, fetched once. The Python script
  // scripts/build_entity_layout.py writes this file from the substrate
  // DB; the UI just renders it. `positionsTick` bumps when the fetch
  // completes so the main effect can re-run and pick up the data.
  const positionsRef = useRefE(null);
  const [positionsTick, setPositionsTick] = useStateE(0);
  useEffectE(() => {
    let cancelled = false;
    fetch('/api/entity-positions')
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (cancelled || !d) return;
        const map = {};
        for (const n of (d.nodes || [])) {
          map[n.id] = { x: n.x, y: n.y };
        }
        positionsRef.current = { map, centroidId: d.centroid_id };
        setPositionsTick(t => t + 1);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffectE(() => {
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

    // Static layout — positions come from the pre-baked
    // entity-positions.json (generated offline by
    // scripts/build_entity_layout.py). The UI does not run any physics;
    // it just renders the baked coordinates. Sim init is gated on the
    // fetch having completed; until then the effect returns early and
    // is re-run when positionsTick bumps.
    if (!simRef.current) {
      const positions = positionsRef.current && positionsRef.current.map;
      if (!positions) {
        // Positions not loaded yet — wait. The separate positions-load
        // effect will bump positionsTick on success, which re-runs this
        // effect (positionsTick is in the dependency list below).
        return;
      }
      const np = nodes.map((n) => {
        const p = positions[n.id];
        return {
          ...n,
          x: p ? p.x : 0,
          y: p ? p.y : 0,
          missing: !p,  // true when the entity didn't exist at bake time
        };
      });
      const idMap = {};
      np.forEach(n => idMap[n.id] = n);
      const ep = edges
        .map(e => ({ ...e, src: idMap[e.source], tgt: idMap[e.target] }))
        .filter(e => e.src && e.tgt);

      // Auto-fit. Compute the bounding box of every placed node, then
      // pick pan/zoom so the graph fills ~85% of the canvas. Missing
      // nodes (no baked position, all at origin) are excluded so they
      // don't anchor the box.
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      for (const n of np) {
        if (n.missing) continue;
        if (n.x < minX) minX = n.x;
        if (n.x > maxX) maxX = n.x;
        if (n.y < minY) minY = n.y;
        if (n.y > maxY) maxY = n.y;
      }
      let zoom = 1, panX = width / 2, panY = height / 2;
      if (isFinite(minX)) {
        const w = maxX - minX, h = maxY - minY;
        // `fit` is the auto-fit ratio that would make the bounding box
        // exactly fill the canvas; `defaultZoomBoost` scales past that
        // so the initial view feels close-up rather than zoomed-out.
        // The periphery clips slightly; the user pans/scrolls to reach
        // it. Upper clamp matches the scroll-wheel maximum so the boost
        // never produces a state the user can't replicate manually.
        const fit = Math.min(
          width / Math.max(w, 1),
          height / Math.max(h, 1),
        );
        const defaultZoomBoost = 1.4;
        zoom = Math.max(0.05, Math.min(2.2, fit * defaultZoomBoost));
        const cx = (minX + maxX) / 2;
        const cy = (minY + maxY) / 2;
        panX = width / 2 - cx * zoom;
        panY = height / 2 - cy * zoom;
      }

      simRef.current = {
        nodes: np, edges: ep, idMap,
        dragging: null, pan: { x: panX, y: panY }, zoom,
        panning: null, running: true,
        wakeUntil: performance.now() + 500,
      };
    }
    const sim = simRef.current;
    // Re-sync sim.edges to the current `edges` arg on every effect run
    // (so live mutations to /api/data appear without a reload). Node
    // positions are preserved via idMap. Newly-created entities since
    // the last bake have x=y=0 and `missing: true` — they appear at
    // the centroid until the next regen.
    for (const id in sim.idMap) {
      // drop stale nodes (deleted from the substrate)
      if (!nodes.find(n => n.id === id)) delete sim.idMap[id];
    }
    for (const n of nodes) {
      if (!sim.idMap[n.id]) {
        const positions = positionsRef.current && positionsRef.current.map;
        const p = positions ? positions[n.id] : null;
        const newNode = {
          ...n,
          x: p ? p.x : 0,
          y: p ? p.y : 0,
          missing: !p,
        };
        sim.nodes.push(newNode);
        sim.idMap[n.id] = newNode;
      } else {
        // refresh label/mentions in case they changed
        Object.assign(sim.idMap[n.id], { label: n.label, mentions: n.mentions });
      }
    }
    sim.nodes = sim.nodes.filter(n => sim.idMap[n.id]);
    sim.edges = edges
      .map(e => ({ ...e, src: sim.idMap[e.source], tgt: sim.idMap[e.target] }))
      .filter(e => e.src && e.tgt);
    const wake = (ms = 600) => {
      sim.wakeUntil = performance.now() + ms;
      if (!sim.running) {
        sim.running = true;
        raf = requestAnimationFrame(step);
      }
    };

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

    const onMouseDown = (e) => {
      const rect = canvas.getBoundingClientRect();
      mouse.x = e.clientX - rect.left;
      mouse.y = e.clientY - rect.top;
      mouse.down = true;
      const n = findNodeAt(mouse.x, mouse.y);
      if (n) {
        sim.dragging = n;
        sim.dragStart = { x: n.x, y: n.y };
        wake(2000);
      } else {
        sim.panning = { startX: mouse.x, startY: mouse.y, panX: sim.pan.x, panY: sim.pan.y };
        wake();
      }
    };
    const onMouseMove = (e) => {
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      mouse.x = sx; mouse.y = sy;
      if (sim.dragging) {
        const w = screenToWorld(sx, sy);
        sim.dragging.x = w.x;
        sim.dragging.y = w.y;
        wake(2000);
      } else if (sim.panning) {
        sim.pan.x = sim.panning.panX + (sx - sim.panning.startX);
        sim.pan.y = sim.panning.panY + (sy - sim.panning.startY);
        wake();
      } else {
        const n = findNodeAt(sx, sy);
        const next = n ? n.id : null;
        setHoverId((prev) => next === prev ? prev : next);
        canvas.style.cursor = n ? 'pointer' : 'grab';
        if (next) wake(150);
      }
    };
    const onMouseUp = (e) => {
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const moved = sim.panning && (Math.abs(sx - sim.panning.startX) + Math.abs(sy - sim.panning.startY) > 4);
      const draggedFar = sim.dragging && sim.dragStart
        && Math.hypot(sim.dragging.x - sim.dragStart.x, sim.dragging.y - sim.dragStart.y) > 4;
      if (sim.dragging) {
        // Capture id locally — sim.dragging is nulled below, but
        // React may invoke the updater after that and would throw
        // reading .id on null.
        const draggedId = sim.dragging.id;
        if (!draggedFar) {
          setSelectedId((prev) => prev === draggedId ? null : draggedId);
        }
        sim.dragging = null;
        sim.dragStart = null;
      } else if (sim.panning && !moved) {
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
      if (n) router.go({ view: 'entity', id: n.id });
    };
    const onWheel = (e) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const factor = Math.exp(-e.deltaY * 0.0015);
      // Wide zoom range — the radial tree layout can stretch hundreds
      // of entities across thousands of pixels for big graphs, so the
      // minimum is set generously to let the user fit it on screen.
      const newZoom = Math.max(0.05, Math.min(3, sim.zoom * factor));
      sim.pan.x = sx - (sx - sim.pan.x) * (newZoom / sim.zoom);
      sim.pan.y = sy - (sy - sim.pan.y) * (newZoom / sim.zoom);
      sim.zoom = newZoom;
      wake();
    };
    const onKeyDown = (e) => { if (e.key === 'Escape') setSelectedId(null); };

    canvas.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    canvas.addEventListener('dblclick', onDblClick);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    window.addEventListener('keydown', onKeyDown);

    const stateRef = { selectedId, hoverId, neighborhood, activeTypes, matchSet, theme: tweaks.theme };
    drawRef.current.state = stateRef;

    // Static render loop. No physics — node positions come from the
    // pre-baked JSON and only change when the user drags a node.
    // The RAF loop runs only as long as something needs to repaint
    // (recent interaction, an active drag, an active pan, or an
    // explicit wake() call from an external state change). When idle
    // the loop self-terminates, costing zero CPU.
    let raf;
    const step = () => {
      const now = performance.now();
      draw();
      if (now < sim.wakeUntil || sim.dragging || sim.panning) {
        raf = requestAnimationFrame(step);
      } else {
        sim.running = false;
      }
    };

    function nodeRadius(n) {
      // Base 7 + small bump for entities mentioned by many statements,
      // so structurally important entities visually pop. Capped so a
      // 200-mention hub doesn't dwarf the rest.
      return 7 + Math.min(n.mentions, 8) * 1.3;
    }

    function draw() {
      const s = drawRef.current.state || stateRef;
      ctx.clearRect(0, 0, width, height);

      ctx.save();
      ctx.translate(sim.pan.x, sim.pan.y);
      ctx.scale(sim.zoom, sim.zoom);

      const edgeAlpha = s.theme === 'dark' ? 0.65 : 0.7;
      const dimAlpha = 0.08;
      const bgColor = s.theme === 'dark' ? '#0a0a0c' : '#ffffff';
      const fgColor = s.theme === 'dark' ? '#f4f4f5' : '#18181b';

      const selNeighbors = new Set();
      const hovNeighbors = new Set();
      if (s.selectedId || s.hoverId) {
        for (const e of sim.edges) {
          if (s.selectedId) {
            if (e.source === s.selectedId) selNeighbors.add(e.target);
            else if (e.target === s.selectedId) selNeighbors.add(e.source);
          }
          if (s.hoverId) {
            if (e.source === s.hoverId) hovNeighbors.add(e.target);
            else if (e.target === s.hoverId) hovNeighbors.add(e.source);
          }
        }
      }

      // Edges. Drawn as directed (small arrowhead near the target).
      for (const e of sim.edges) {
        if (!s.activeTypes.has(e.link_type)) continue;
        const inHood = !s.neighborhood || (s.neighborhood.has(e.source) && s.neighborhood.has(e.target));
        if (s.neighborhood && !inHood) continue;
        const incidentToSel = s.selectedId && (e.source === s.selectedId || e.target === s.selectedId);
        const incidentToHover = s.hoverId && (e.source === s.hoverId || e.target === s.hoverId);
        // Search dim: if a query is active and neither endpoint matches,
        // the edge is irrelevant context. Selection/hover take priority
        // over search when both are active.
        const searchDim = s.matchSet && !s.matchSet.has(e.source) && !s.matchSet.has(e.target);
        const dim = (s.selectedId || s.hoverId)
          ? !(incidentToSel || incidentToHover)
          : searchDim;

        ctx.strokeStyle = entityLinkColor(e.link_type, s.theme);
        ctx.fillStyle = ctx.strokeStyle;
        ctx.globalAlpha = dim ? dimAlpha : edgeAlpha;
        ctx.lineWidth = (incidentToSel || incidentToHover) ? 2.2 : 1.6;

        ctx.beginPath();
        ctx.moveTo(e.src.x, e.src.y);
        ctx.lineTo(e.tgt.x, e.tgt.y);
        ctx.stroke();

        // Arrowhead at the target, offset by the target's radius so it
        // doesn't get buried inside the diamond.
        const dx = e.tgt.x - e.src.x;
        const dy = e.tgt.y - e.src.y;
        const len = Math.hypot(dx, dy) || 1;
        const ux = dx / len, uy = dy / len;
        const tr = nodeRadius(e.tgt) + 4;
        const tipX = e.tgt.x - ux * tr;
        const tipY = e.tgt.y - uy * tr;
        const ah = 7;  // arrowhead length
        const aw = 4;  // half-width
        ctx.beginPath();
        ctx.moveTo(tipX, tipY);
        ctx.lineTo(tipX - ux * ah - uy * aw, tipY - uy * ah + ux * aw);
        ctx.lineTo(tipX - ux * ah + uy * aw, tipY - uy * ah - ux * aw);
        ctx.closePath();
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      // Nodes — diamonds, matching GraphView's entity convention.
      for (const n of sim.nodes) {
        if (s.neighborhood && !s.neighborhood.has(n.id)) continue;
        const isSel = n.id === s.selectedId;
        const isHov = n.id === s.hoverId;
        const isMatch = s.matchSet ? s.matchSet.has(n.id) : false;
        // Selection/hover dimming takes precedence; search dimming
        // only kicks in when neither is active. A match is never dimmed
        // by search even if it's far from a selection.
        const focusActive = s.selectedId || s.hoverId;
        const dim = focusActive
          ? !isSel && !isHov &&
            !(s.selectedId && selNeighbors.has(n.id)) &&
            !(s.hoverId && hovNeighbors.has(n.id))
          : (s.matchSet ? !isMatch : false);

        ctx.globalAlpha = dim ? 0.25 : 1;
        const r = nodeRadius(n) * (isSel ? 1.4 : isHov ? 1.2 : isMatch ? 1.15 : 1);

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

        // Search-match halo. Drawn first so a selection/hover ring on
        // the same node still wins on top.
        if (isMatch && !isSel && !isHov) {
          ctx.strokeStyle = s.theme === 'dark' ? '#facc15' : '#ca8a04';
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(n.x, n.y, r + 5, 0, Math.PI * 2);
          ctx.stroke();
        }

        if (isSel || isHov) {
          ctx.strokeStyle = s.theme === 'dark' ? '#60a5fa' : '#2563eb';
          ctx.lineWidth = 1.4;
          ctx.beginPath();
          ctx.arc(n.x, n.y, r + 5, 0, Math.PI * 2);
          ctx.stroke();
        }

        // Label — always visible for entities since N is small.
        const label = n.label.length > 36 ? n.label.slice(0, 33) + '…' : n.label;
        ctx.font = `${(isSel || isHov) ? '600 ' : '500 '}${12 / Math.max(1, sim.zoom * 0.9)}px Inter, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.lineWidth = 3 / sim.zoom;
        ctx.strokeStyle = bgColor;
        ctx.strokeText(label, n.x, n.y + r + 4);
        ctx.fillStyle = fgColor;
        ctx.fillText(label, n.x, n.y + r + 4);
        ctx.globalAlpha = 1;
      }

      ctx.restore();
    }

    drawRef.current.draw = draw;
    // Centre a node on screen at a sensible zoom level. Used by the
    // search "jump" buttons so the user can flip through matches and
    // actually see each one without manually panning. The zoom target
    // (default 1.4) is enough to read the node's label comfortably
    // without losing the surrounding neighbourhood.
    drawRef.current.focusNode = (nodeId, zoom = 1.4) => {
      const n = sim.idMap && sim.idMap[nodeId];
      if (!n) return;
      sim.zoom = zoom;
      sim.pan.x = width / 2 - n.x * zoom;
      sim.pan.y = height / 2 - n.y * zoom;
      sim.wakeUntil = performance.now() + 250;
      if (!sim.running) {
        sim.running = true;
        raf = requestAnimationFrame(step);
      }
    };
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

  useEffectE(() => {
    drawRef.current.state = { selectedId, hoverId, neighborhood, activeTypes, matchSet, theme: tweaks.theme };
    const sim = simRef.current;
    if (sim) {
      sim.wakeUntil = performance.now() + 200;
      if (!sim.running && drawRef.current.requestStep) drawRef.current.requestStep();
    }
  }, [selectedId, hoverId, neighborhood, activeTypes, matchSet, tweaks.theme]);

  useEffectE(() => { if (focusId) setSelectedId(focusId); }, [focusId]);

  const selected = selectedId ? idx.byId[selectedId] : null;
  const selectedNeighbors = selected && selected.kind === 'entity' ? (() => {
    const out = [];
    (idx.entityOutgoing[selected.id] || []).forEach(l => {
      const target = idx.byId[l.to];
      if (target) out.push({ dir: 'out', link_type: l.link_type, target });
    });
    (idx.entityIncoming[selected.id] || []).forEach(l => {
      const target = idx.byId[l.from];
      if (target) out.push({ dir: 'in', link_type: l.link_type, target });
    });
    return out;
  })() : [];

  const aliasNames = selected && selected.kind === 'entity'
    ? (idx.namesByEntity[selected.id] || []).filter(n => n.text !== selected.name).map(n => n.text)
    : [];

  const noEntities = data.entities.length === 0;
  const noLinks = (data.entity_links || []).length === 0;

  // Sorted entity list for the target-picker datalist. Sort is by
  // primary name, lowercased — keeps the "alice/Bob/charlie" order
  // intuitive regardless of casing in the source data.
  const sortedEntities = useMemoE(
    () => [...data.entities].sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase())),
    [data, version],
  );

  const { refresh } = useDataCtx();
  const [adding, setAdding] = useStateE(false);
  const [pendingRemove, setPendingRemove] = useStateE(null);

  const removeLink = async (n) => {
    const from_entity_id = n.dir === 'out' ? selected.id : n.target.id;
    const to_entity_id = n.dir === 'out' ? n.target.id : selected.id;
    const key = `${from_entity_id}→${to_entity_id}|${n.link_type}`;
    setPendingRemove(key);
    try {
      await postJSON('/remove-entity-links', {
        links: [{ from_entity_id, to_entity_id, link_type: n.link_type }],
      });
      await refresh();
    } catch (e) {
      console.error('remove-entity-links failed', e);
      alert(`Failed to remove link: ${e.message || e}`);
    }
    setPendingRemove(null);
  };

  // Reset add-form state when the user navigates to a different entity.
  useEffectE(() => { setAdding(false); }, [selectedId]);

  // Ordered list of matched entity ids — same order as the
  // sortedEntities datalist (primary name, lowercased). Used by the
  // prev/next jump buttons so stepping through matches is
  // deterministic regardless of canvas geometry.
  const matchList = useMemoE(() => {
    if (!matchSet) return [];
    return sortedEntities.filter(en => matchSet.has(en.id)).map(en => en.id);
  }, [matchSet, sortedEntities]);
  const [matchIndex, setMatchIndex] = useStateE(0);
  // Reset the cursor whenever the query changes so the next jump
  // starts from the first match rather than wherever the user left
  // off in a previous search.
  useEffectE(() => { setMatchIndex(0); }, [searchQuery, showIslands]);

  const jumpToMatch = (delta) => {
    if (matchList.length === 0) return;
    const next = ((matchIndex + delta) % matchList.length + matchList.length) % matchList.length;
    setMatchIndex(next);
    const id = matchList[next];
    setSelectedId(id);
    if (drawRef.current.focusNode) drawRef.current.focusNode(id);
  };

  return (
    <div className="graph-page">
      <div className="graph-canvas-wrap" ref={containerRef}>
        <canvas ref={canvasRef} className="graph-canvas" />

        <div className="graph-toolbar">
          <div className="ent-search">
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Escape') setSearchQuery('');
                if (e.key === 'Enter' && matchList.length > 0) {
                  // Enter advances through matches like the next-button,
                  // so repeated Enter presses cycle through the list.
                  jumpToMatch(e.shiftKey ? -1 : 1);
                }
              }}
              placeholder="search entities…"
              spellCheck={false}
            />
            <button
              type="button"
              className="ent-search-jump"
              onClick={() => jumpToMatch(-1)}
              disabled={matchList.length === 0}
              title="Previous match (Shift+Enter)"
              aria-label="Previous match"
            >‹</button>
            <button
              type="button"
              className="ent-search-jump"
              onClick={() => jumpToMatch(1)}
              disabled={matchList.length === 0}
              title="Next match (Enter)"
              aria-label="Next match"
            >›</button>
            {(matchSet || showIslands) && (
              <span className="ent-search-count">
                {matchList.length > 0
                  ? `${matchIndex + 1} / ${matchList.length}${showIslands ? ' island' + (matchList.length === 1 ? '' : 's') : ''}`
                  : showIslands ? `0 islands` : `0 matches`}
              </span>
            )}
          </div>
          <button className={`graph-pill${focusMode ? '' : ' is-off'}`} onClick={() => setFocusMode(v => !v)}>
            <span className="swatch" style={{background: 'currentColor'}} />
            {focusMode ? 'focus mode · on' : 'focus mode · off'}
          </button>
          <button
            className={`graph-pill${showIslands ? ' is-primary' : ' is-off'}`}
            onClick={() => setShowIslands(v => !v)}
            title="Highlight entities that aren't part of the biggest connected component, including small disconnected clusters"
          >
            🏝 islands{islandIds.size > 0 ? ` · ${islandIds.size}` : ''}
          </button>
          <button
            className={`graph-pill${editMode ? ' is-primary' : ' is-off'}`}
            onClick={() => setTweak('showEditAffordances', !editMode)}
            title={editMode ? 'Disable edit affordances' : 'Enable edit affordances'}
          >
            ✎ {editMode ? 'edit · on' : 'edit · off'}
          </button>
          <span className="graph-pill is-off" style={{cursor:'default'}}>
            <span className="swatch" style={{background: tweaks.theme === 'dark' ? '#22d3ee' : '#0e7490', transform:'rotate(45deg)'}} />
            entities · {data.entities.length}
          </span>
          {allEntityLinkTypes.length === 0 && (
            <span className="graph-pill is-off" style={{cursor:'default'}}>
              no entity links yet
            </span>
          )}
          {allEntityLinkTypes.map(t => {
            const on = activeTypes.has(t);
            const count = entityLinkTypeCounts[t] || 0;
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
                title={`${t} · ${count} edge${count === 1 ? '' : 's'}`}
              >
                <span className="swatch" style={{background: entityLinkColor(t, tweaks.theme), height: 8, borderRadius: 2}} />
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

      <aside className="graph-side">
        {!selected && (
          <div>
            <h3>Entities</h3>
            <div className="graph-empty-state">
              {noEntities
                ? 'No entities in the substrate yet. Create one with upsert_entity (or upsert_name to alias it); statements that mention it by name then link automatically.'
                : noLinks
                  ? 'No entity↔entity links recorded yet. Use add_entity_links to record structural relationships (parent/subsidiary, category/member, etc.); they will draw here.'
                  : 'Click an entity to select it; double-click to open its detail view. Toggle a link type in the toolbar to fade it out.'}
            </div>
          </div>
        )}

        {selected && selected.kind === 'entity' && (
          <>
            <div>
              <KindTag kind="entity" />
              <div className="graph-focus-title" style={{marginTop:8}}>{selected.name}</div>
              <div style={{fontFamily:'var(--mono)', fontSize:10.5, color:'var(--ink-4)', marginTop:4}}>{selected.id}</div>

              {aliasNames.length > 0 && (
                <div style={{marginTop:10, display:'flex', gap:6, flexWrap:'wrap'}}>
                  {aliasNames.map(a => (
                    <span key={a} style={{
                      fontFamily:'var(--mono)', fontSize:10.5, color:'var(--ink-3)',
                      padding:'2px 6px', border:'1px dashed var(--rule)', borderRadius:3,
                    }}>{a}</span>
                  ))}
                </div>
              )}

              {selected.description && (
                <p style={{fontSize:13, color:'var(--ink-2)', marginTop:12, lineHeight:1.55}}>
                  {selected.description}
                </p>
              )}

              <div style={{marginTop:14, fontFamily:'var(--mono)', fontSize:11, color:'var(--ink-4)'}}>
                mentioned by {(idx.mentionsByEntity[selected.id] || []).length} statement(s)
              </div>

              <div style={{marginTop:18, display:'flex', gap:10}}>
                <button
                  className="graph-pill"
                  onClick={() => router.go({ view: 'entity', id: selected.id })}
                  style={{color:'var(--accent)', borderColor:'var(--accent)'}}
                >
                  open detail →
                </button>
              </div>
            </div>

            <div>
              <div style={{display:'flex', alignItems:'baseline', justifyContent:'space-between', gap:8}}>
                <h3 style={{margin:0}}>Entity links · {selectedNeighbors.length}</h3>
                {editMode && !adding && (
                  <button
                    className="graph-pill is-primary"
                    onClick={() => setAdding(true)}
                    title="Add a new entity↔entity link from this entity"
                  >
                    + add link
                  </button>
                )}
              </div>

              {editMode && adding && (
                <EntityLinkAddForm
                  self={selected}
                  entities={sortedEntities}
                  knownTypes={allEntityLinkTypes}
                  onCreated={async () => { await refresh(); setAdding(false); }}
                  onCancel={() => setAdding(false)}
                />
              )}

              <div style={{display:'flex', flexDirection:'column', gap:6, marginTop:10}}>
                {selectedNeighbors.length === 0 && (
                  <div className="graph-empty-state">No entity↔entity links on this entity.</div>
                )}
                {selectedNeighbors.map((n, i) => {
                  const fromId = n.dir === 'out' ? selected.id : n.target.id;
                  const toId = n.dir === 'out' ? n.target.id : selected.id;
                  const key = `${fromId}→${toId}|${n.link_type}`;
                  const removing = pendingRemove === key;
                  return (
                    <div
                      key={key}
                      style={{
                        display:'grid',
                        gridTemplateColumns: editMode ? 'auto 1fr auto' : 'auto 1fr',
                        gap:10,
                        padding:'8px 0',
                        borderBottom:'1px dashed var(--rule)',
                        alignItems:'baseline',
                        opacity: removing ? 0.5 : 1,
                      }}
                    >
                      <span
                        onClick={() => setSelectedId(n.target.id)}
                        style={{
                          whiteSpace:'nowrap', fontFamily:'var(--mono)', fontSize:10.5,
                          color: entityLinkColor(n.link_type, tweaks.theme),
                          cursor:'pointer',
                        }}
                      >
                        {n.dir === 'out' ? '↗ ' : '↙ '}{n.link_type}
                      </span>
                      <span
                        onClick={() => setSelectedId(n.target.id)}
                        style={{fontSize:12.5, color:'var(--ink)', lineHeight:1.4, cursor:'pointer'}}
                      >
                        {n.target.name}
                      </span>
                      {editMode && (
                        <button
                          className="ent-edit-remove"
                          onClick={() => removeLink(n)}
                          disabled={removing}
                          title="Remove this entity link"
                          aria-label="Remove this entity link"
                        >
                          ×
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}

Object.assign(window, { EntitiesGraph });
