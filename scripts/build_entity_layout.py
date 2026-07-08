"""Offline entity-graph layout baker.

Reads the entity nodes and entity-to-entity links from the substrate DB,
runs a ForceAtlas2-style layout in LinLog mode, and writes the resulting
2D coordinates to ``src/mycelium/ui/data/entity-positions.json`` for the
web UI to render statically.

The algorithm:

  - Repulsion: every node repels every other with force proportional to
    (1 + deg(i)) * (1 + deg(j)) / dist. Hubs push harder.
  - Attraction (LinLog): every edge pulls its endpoints with force
    log(1 + dist). Compared to linear attraction this produces visibly
    more separation between clusters — the property we want.
  - Gravity: each node is pulled toward the origin with force
    proportional to (1 + deg) * dist (mild — just keeps things from
    drifting off to infinity).
  - Integration: Barnes-Hut would be faster, but for a few thousand
    nodes the O(N²) loop in numpy is fine (vectorised, ~100ms/iter).

Run:
    python scripts/build_entity_layout.py
    python scripts/build_entity_layout.py --iters 1500 --seed 42

Output is deterministic given the same seed and substrate state.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / ".mycelium" / "mycelium.db"
DEFAULT_OUTPUT = (
    REPO_ROOT / "src" / "mycelium" / "ui" / "data" / "entity-positions.json"
)


def load_graph(db_path: Path) -> tuple[list[dict], list[tuple[int, int]]]:
    """Pull entities + their (deduplicated, undirected) link list."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    name_rows = conn.execute("SELECT entity_id, text FROM names").fetchall()
    primary_name: dict[str, str] = {}
    for r in sorted(name_rows, key=lambda r: r["text"]):
        primary_name.setdefault(r["entity_id"], r["text"])

    entity_rows = conn.execute("SELECT id FROM entities").fetchall()
    entities = [
        {"id": r["id"], "name": primary_name.get(r["id"], r["id"])} for r in entity_rows
    ]

    id_to_idx = {e["id"]: i for i, e in enumerate(entities)}

    link_rows = conn.execute(
        "SELECT from_entity_id, to_entity_id FROM entity_links"
    ).fetchall()
    seen: set[tuple[int, int]] = set()
    edges: list[tuple[int, int]] = []
    for r in link_rows:
        a = id_to_idx.get(r["from_entity_id"])
        b = id_to_idx.get(r["to_entity_id"])
        if a is None or b is None or a == b:
            continue
        lo, hi = (a, b) if a < b else (b, a)
        if (lo, hi) in seen:
            continue
        seen.add((lo, hi))
        edges.append((lo, hi))

    conn.close()
    return entities, edges


def compute_degree(n: int, edges: list[tuple[int, int]]) -> np.ndarray:
    deg = np.zeros(n, dtype=np.float64)
    for a, b in edges:
        deg[a] += 1
        deg[b] += 1
    return deg


def connected_components(n: int, edges: list[tuple[int, int]]) -> np.ndarray:
    """Return an array of component ids, one per node."""
    adj: list[list[int]] = [[] for _ in range(n)]
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    comp = np.full(n, -1, dtype=np.int64)
    cid = 0
    for start in range(n):
        if comp[start] != -1:
            continue
        comp[start] = cid
        stack = [start]
        while stack:
            cur = stack.pop()
            for nb in adj[cur]:
                if comp[nb] == -1:
                    comp[nb] = cid
                    stack.append(nb)
        cid += 1
    return comp


def graph_centroid(n: int, edges: list[tuple[int, int]], comp: np.ndarray) -> int:
    """Pick the 1-median vertex of the largest component (min sum of
    shortest-path distances to other nodes in the same component)."""
    # find largest component
    counts = np.bincount(comp)
    largest = int(np.argmax(counts))
    members = np.where(comp == largest)[0]
    member_set = set(int(x) for x in members)

    adj: list[list[int]] = [[] for _ in range(n)]
    for a, b in edges:
        if a in member_set and b in member_set:
            adj[a].append(b)
            adj[b].append(a)

    best_node = int(members[0])
    best_sum = float("inf")
    for src in members:
        src = int(src)
        dist = {src: 0}
        q = deque([src])
        s = 0
        while q:
            cur = q.popleft()
            d = dist[cur]
            s += d
            for nb in adj[cur]:
                if nb not in dist:
                    dist[nb] = d + 1
                    q.append(nb)
            if s >= best_sum:
                # early exit — no chance of beating the current best
                s = float("inf")
                break
        if s < best_sum:
            best_sum = s
            best_node = src
    return best_node


def _component_membership(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    """Return the list of connected components, each as a list of node indices."""
    adj: list[list[int]] = [[] for _ in range(n)]
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    seen = [False] * n
    comps: list[list[int]] = []
    for start in range(n):
        if seen[start]:
            continue
        members: list[int] = []
        stack = [start]
        while stack:
            u = stack.pop()
            if seen[u]:
                continue
            seen[u] = True
            members.append(u)
            for v in adj[u]:
                if not seen[v]:
                    stack.append(v)
        comps.append(members)
    comps.sort(key=lambda c: -len(c))
    return comps


def _all_pairs_shortest_paths(
    members: list[int],
    edges: list[tuple[int, int]],
    edge_weight: np.ndarray | None = None,
) -> np.ndarray:
    """Shortest-path distances from every node in `members` to every
    other. ``edge_weight`` is a per-edge weight array aligned with the
    full ``edges`` list — when omitted, every edge counts as 1 hop and
    BFS is used. When present, Dijkstra is used.

    Edges touching nodes outside `members` are ignored."""
    local_index = {g: i for i, g in enumerate(members)}
    k = len(members)
    adj_local: list[list[tuple[int, float]]] = [[] for _ in range(k)]
    for ei, (a, b) in enumerate(edges):
        if a in local_index and b in local_index:
            ai, bi = local_index[a], local_index[b]
            w = float(edge_weight[ei]) if edge_weight is not None else 1.0
            adj_local[ai].append((bi, w))
            adj_local[bi].append((ai, w))

    D = np.full((k, k), np.inf, dtype=np.float64)
    if edge_weight is None:
        # Unweighted — BFS is faster than Dijkstra.
        for src in range(k):
            D[src, src] = 0.0
            q = deque([src])
            while q:
                u = q.popleft()
                du = D[src, u]
                for v, _ in adj_local[u]:
                    if D[src, v] == np.inf:
                        D[src, v] = du + 1
                        q.append(v)
    else:
        import heapq

        for src in range(k):
            D[src, src] = 0.0
            heap: list[tuple[float, int]] = [(0.0, src)]
            while heap:
                du, u = heapq.heappop(heap)
                if du > D[src, u]:
                    continue
                for v, w in adj_local[u]:
                    nd = du + w
                    if nd < D[src, v]:
                        D[src, v] = nd
                        heapq.heappush(heap, (nd, v))
    return D


def stress_majorization(
    n: int,
    edges: list[tuple[int, int]],
    *,
    iters: int = 300,
    seed: int = 42,
    component_pad: float = 4.0,
    edge_weight: np.ndarray | None = None,
) -> np.ndarray:
    """Stress majorization layout.

    For each connected component independently we minimise
        σ(X) = Σ_{i<j} w_ij (||x_i - x_j|| - d_ij)²
    where d_ij is the unweighted shortest-path distance (hop count)
    between i and j, and w_ij = 1/d_ij². The minimisation uses the
    standard localised update: each node moves to the weighted average
    of the positions it "wants" to be at relative to every other node.
    No gravity, no global repulsion — distance preservation is the only
    objective, which lets clusters spread into whatever overall shape
    fits best instead of being squashed into a circle.

    Disconnected components have no edges between them; we lay each one
    out independently and then pack their centres with a phyllotaxis.

    Args:
        component_pad — gap (in graph-distance units) between adjacent
            component bounding circles during packing.

    Returns an (n, 2) position array in graph-distance units (one unit
    ≈ "one hop apart"); the caller normalises to canvas pixels.
    """
    rng = np.random.default_rng(seed)
    pos = rng.normal(0.0, 1.0, size=(n, 2)).astype(np.float64)

    comps = _component_membership(n, edges)

    # Lay out each component on its own.
    comp_radii: list[float] = []
    for members in comps:
        k = len(members)
        idx = np.array(members, dtype=np.int64)
        if k == 1:
            pos[idx] = 0.0
            comp_radii.append(0.0)
            continue
        D = _all_pairs_shortest_paths(members, edges, edge_weight=edge_weight)
        # Weights: 1/d². Disconnected (shouldn't happen within a
        # component, but defensive) → 0.
        with np.errstate(divide="ignore", invalid="ignore"):
            W = np.where(D > 0, 1.0 / (D * D), 0.0)
        W = np.where(np.isfinite(W), W, 0.0)
        W_sum = W.sum(axis=1)  # (k,)

        X = rng.normal(0.0, np.sqrt(k), size=(k, 2))  # spread proportional to √k

        for _ in range(iters):
            # Per-node update: new_x_i = (Σ_j w_ij * (x_j + d_ij * (x_i - x_j) / |x_i - x_j|)) / Σ_j w_ij
            delta = X[:, None, :] - X[None, :, :]  # (k, k, 2)
            dist = np.sqrt((delta**2).sum(axis=-1)) + 1e-9  # (k, k)
            unit = delta / dist[..., None]  # (k, k, 2)
            # ideal[i, j, :] = x_j + d_ij * unit[i, j]
            ideal = X[None, :, :] + D[..., None] * unit
            # Mask invalid (j=i, or D=inf) → contribute nothing
            mask = (D > 0) & np.isfinite(D)
            ideal = np.where(mask[..., None], ideal * W[..., None], 0.0)
            numerator = ideal.sum(axis=1)  # (k, 2)
            X = numerator / (W_sum[:, None] + 1e-12)

        # Centre this component on origin, record its radius for packing.
        X -= X.mean(axis=0)
        radius = float(np.sqrt((X**2).sum(axis=1)).max())
        comp_radii.append(radius)
        pos[idx] = X

    # Pack components via phyllotaxis. The first (largest) sits at the
    # origin; subsequent ones spiral outward at golden-angle steps with
    # a radius scaled so their bounding circles don't overlap.
    golden = np.pi * (3 - np.sqrt(5))
    cursor_r = 0.0
    centres: list[tuple[float, float]] = [(0.0, 0.0)]
    for i in range(1, len(comps)):
        # Place this component's centre at a distance that clears its
        # own bounding circle plus the largest one we've placed so far,
        # plus the user-configurable pad.
        cursor_r = max(cursor_r, comp_radii[0]) + comp_radii[i] + component_pad
        angle = i * golden
        centres.append((cursor_r * np.cos(angle), cursor_r * np.sin(angle)))

    for members, (cx, cy) in zip(comps, centres, strict=False):
        idx = np.array(members, dtype=np.int64)
        pos[idx, 0] += cx
        pos[idx, 1] += cy

    return pos


def relax_overlaps(
    pos: np.ndarray,
    deg: np.ndarray,
    *,
    min_dist: float = 0.7,
    iters: int = 120,
    step: float = 0.5,
) -> np.ndarray:
    """Mass-weighted overlap relaxation.

    All pairs share a single small ``min_dist`` threshold — the goal is
    just to keep the visible diamonds from overlapping, not to redo
    the layout. The clever part is *how* the push is distributed when
    a pair is too close:

        push_share_i = mass_j / (mass_i + mass_j)
        push_share_j = mass_i / (mass_i + mass_j)

    where mass = 1 + degree. So a hub paired with a satellite barely
    moves (hub mass is huge, its share of the push is small) while the
    satellite does almost all the moving. That preserves the SM-placed
    hub positions and "ripples" satellites outward into a clean ring
    around their hub.

    Leaf↔leaf pairs split the push evenly (both masses = 2), which is
    fine because the pair has a small deficit by definition (the SM
    already placed unrelated leaves apart).
    """
    mass = 1.0 + np.asarray(deg, dtype=np.float64)
    share_i = mass[None, :] / (
        mass[:, None] + mass[None, :]
    )  # share for row i from pair (i,j)
    for _ in range(iters):
        dx = pos[:, 0:1] - pos[:, 0:1].T
        dy = pos[:, 1:2] - pos[:, 1:2].T
        dist2 = dx * dx + dy * dy
        np.fill_diagonal(dist2, np.inf)
        dist = np.sqrt(dist2)
        deficit = np.maximum(0.0, min_dist - dist)
        if deficit.size == 0 or deficit.max() < 1e-4:
            break
        # Unit vector from j to i is (dx, dy)/dist. We push i in that
        # direction by `step * deficit * share_i`. Reciprocally for j.
        push = step * deficit * share_i / (dist + 1e-9)
        push_x = (push * dx).sum(axis=1)
        push_y = (push * dy).sum(axis=1)
        pos[:, 0] += push_x
        pos[:, 1] += push_y
    return pos


def force_atlas_linlog(
    n: int,
    edges: list[tuple[int, int]],
    deg: np.ndarray,
    *,
    iters: int = 1200,
    seed: int = 42,
    scaling: float = 30.0,
    gravity: float = 0.5,
    dissuade_hubs: bool = True,
) -> np.ndarray:
    """Vectorised ForceAtlas2 in LinLog attraction mode with optional
    "dissuade hubs". Returns an (n, 2) float array of positions.

    Knobs that control visible clustering:
        scaling       — repulsion strength. Higher = clusters pushed further apart.
        gravity       — unit-vector pull toward origin (NOT Hooke spring;
                        same magnitude at any distance). Just barely strong
                        enough to stop disconnected nodes drifting off.
        dissuade_hubs — divides attraction by the endpoint's mass. Heavy
                        hub nodes get pulled toward their satellites less,
                        so they sit at the centre of their cluster instead
                        of being yanked toward neighbouring hubs.
    """
    rng = np.random.default_rng(seed)
    # Larger initial scatter so the first iterations don't waste energy
    # untangling a dense pile. Range ≈ ±50 — enough to give the LinLog
    # attraction non-trivial edge lengths to work with from frame 1.
    pos = rng.normal(0.0, 50.0, size=(n, 2)).astype(np.float64)
    mass = 1.0 + deg  # ForceAtlas2 convention

    edge_arr = (
        np.array(edges, dtype=np.int64) if edges else np.zeros((0, 2), dtype=np.int64)
    )
    src_idx = edge_arr[:, 0]
    dst_idx = edge_arr[:, 1]

    speed = 1.0
    speed_eff_max = 10.0

    for _it in range(iters):
        # ---- Repulsion (all-pairs, vectorised). O(N²).
        dx = pos[:, 0:1] - pos[:, 0:1].T
        dy = pos[:, 1:2] - pos[:, 1:2].T
        dist2 = dx * dx + dy * dy
        np.fill_diagonal(dist2, 1.0)
        coeff = scaling * np.outer(mass, mass) / dist2
        fx = (coeff * dx).sum(axis=1)
        fy = (coeff * dy).sum(axis=1)

        # ---- Attraction (LinLog). For each edge the unit pull magnitude
        # is log(1 + d). With dissuade_hubs, the pull on each endpoint
        # is divided by that endpoint's mass — heavy hubs barely move
        # toward their satellites, so two hubs sharing a satellite no
        # longer get yanked together via that satellite as a fulcrum.
        if edge_arr.size:
            ex = pos[dst_idx, 0] - pos[src_idx, 0]
            ey = pos[dst_idx, 1] - pos[src_idx, 1]
            ed = np.sqrt(ex * ex + ey * ey) + 1e-9
            f = np.log1p(ed) / ed
            if dissuade_hubs:
                f_src = f / mass[src_idx]
                f_dst = f / mass[dst_idx]
            else:
                f_src = f
                f_dst = f
            np.add.at(fx, src_idx, f_src * ex)
            np.add.at(fy, src_idx, f_src * ey)
            np.add.at(fx, dst_idx, -f_dst * ex)
            np.add.at(fy, dst_idx, -f_dst * ey)

        # ---- Gravity. FA2 standard: constant-magnitude pull toward
        # origin (NOT a Hooke spring). Same strength at r=10 as r=10000,
        # so it cannot overpower repulsion at any scale — it just stops
        # nodes drifting off to infinity.
        r = np.sqrt(pos[:, 0] ** 2 + pos[:, 1] ** 2) + 1e-9
        gx = -gravity * mass * pos[:, 0] / r
        gy = -gravity * mass * pos[:, 1] / r
        fx += gx
        fy += gy

        # ---- Adaptive speed (FA2 style).
        force_mag = np.sqrt(fx * fx + fy * fy) + 1e-9
        # damping per-node — heavier nodes move slower (the same
        # mechanism that produces the "settled hub" look)
        traction = speed / (1.0 + np.sqrt(speed * force_mag))
        eff = np.minimum(traction, speed_eff_max / force_mag)
        pos[:, 0] += fx * eff
        pos[:, 1] += fy * eff

        # cool down over time so the last iterations are fine-tuning
        speed = max(0.05, speed * 0.995)

    return pos


def normalize_positions(pos: np.ndarray, target_radius: float = 2000.0) -> np.ndarray:
    """Centre on origin and scale so the 95th-percentile radius equals
    ``target_radius``. Robust to a handful of far-flung outliers."""
    pos = pos - pos.mean(axis=0)
    r = np.sqrt((pos**2).sum(axis=1))
    p95 = np.percentile(r, 95)
    if p95 > 1e-6:
        pos *= target_radius / p95
    return pos


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument(
        "--algorithm",
        choices=["sm", "fa2"],
        default="sm",
        help="sm = stress majorization (default, best cluster shapes); "
        "fa2 = ForceAtlas2 LinLog (force-directed, circular envelope)",
    )
    ap.add_argument(
        "--iters",
        type=int,
        default=None,
        help="iteration count (defaults: 300 for sm, 1200 for fa2)",
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--scaling", type=float, default=30.0, help="fa2: repulsion strength"
    )
    ap.add_argument("--gravity", type=float, default=0.5, help="fa2 only")
    ap.add_argument(
        "--no-dissuade-hubs",
        action="store_true",
        help="fa2: disable the dissuade-hubs attraction mode",
    )
    ap.add_argument("--target-radius", type=float, default=2500.0)
    ap.add_argument(
        "--hub-edge-scale",
        type=float,
        default=0.08,
        help="sm: edges incident to a degree-K node count as "
        "(1 + alpha * K) graph-hops instead of 1. Pushes "
        "hubs further from their satellites and (through "
        "shared neighbours) further from other hubs. "
        "Tunable: 0 disables (pure unweighted SM); 0.05 is "
        "modest; 0.15 is very pronounced.",
    )
    ap.add_argument(
        "--min-dist",
        type=float,
        default=0.3,
        help="sm: tiny overlap-prevention min distance "
        "(graph-hop units). Mass-weighted so hubs don't "
        "move. Set 0 to disable.",
    )
    args = ap.parse_args()

    if not args.db.exists():
        raise SystemExit(f"DB not found: {args.db}")

    print(f"loading graph from {args.db} …")
    entities, edges = load_graph(args.db)
    n = len(entities)
    print(f"  {n} entities, {len(edges)} unique undirected entity-links")

    deg = compute_degree(n, edges)
    comp = connected_components(n, edges)
    n_components = int(comp.max()) + 1 if n else 0
    print(f"  {n_components} connected components")

    centroid_idx = graph_centroid(n, edges, comp) if n else None
    centroid_id = entities[centroid_idx]["id"] if centroid_idx is not None else None
    print(f"  centroid: {centroid_id}")

    if args.algorithm == "sm":
        iters = args.iters if args.iters is not None else 300
        # Per-edge weight: (1 + alpha * max(deg_a, deg_b)). Edges
        # touching a degree-100 hub count as ~9 hops with alpha=0.08.
        edge_weight: np.ndarray | None = None
        if args.hub_edge_scale > 0 and edges:
            # Edges where one endpoint is a pendant (degree-1 leaf with no
            # other connections) keep weight=1 — pendants sit one hop from
            # their parent, just like in unweighted SM. Every other edge
            # is scaled by max-endpoint-degree, which spreads hubs apart
            # from each other and from bridging multi-connected entities.
            ew = np.empty(len(edges), dtype=np.float64)
            for i, (a, b) in enumerate(edges):
                if min(deg[a], deg[b]) == 1:
                    ew[i] = 1.0
                else:
                    ew[i] = 1.0 + args.hub_edge_scale * max(deg[a], deg[b])
            edge_weight = ew
            n_pendant = int((ew == 1.0).sum())
            print(
                f"running stress majorization for {iters} iterations "
                f"(hub_edge_scale={args.hub_edge_scale}, "
                f"{n_pendant}/{len(edges)} pendant edges) …"
            )
        else:
            print(f"running stress majorization for {iters} iterations (unweighted) …")
        pos = stress_majorization(
            n,
            edges,
            iters=iters,
            seed=args.seed,
            edge_weight=edge_weight,
        )
        if args.min_dist > 0:
            print(f"relaxing overlaps (min_dist={args.min_dist}) …")
            pos = relax_overlaps(pos, deg, min_dist=args.min_dist)
    else:
        iters = args.iters if args.iters is not None else 1200
        print(f"running ForceAtlas2 LinLog for {iters} iterations …")
        pos = force_atlas_linlog(
            n,
            edges,
            deg,
            iters=iters,
            seed=args.seed,
            scaling=args.scaling,
            gravity=args.gravity,
            dissuade_hubs=not args.no_dissuade_hubs,
        )
    pos = normalize_positions(pos, target_radius=args.target_radius)

    nodes = [
        {
            "id": entities[i]["id"],
            "name": entities[i]["name"],
            "x": float(pos[i, 0]),
            "y": float(pos[i, 1]),
            "degree": int(deg[i]),
            "component": int(comp[i]),
        }
        for i in range(n)
    ]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "algorithm": args.algorithm,
        "iters": iters,
        "scaling": args.scaling,
        "gravity": args.gravity,
        "n_components": n_components,
        "centroid_id": centroid_id,
        "nodes": nodes,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2))
    sz = os.path.getsize(args.output) / 1024
    print(f"wrote {args.output} ({sz:.1f} KB)")


if __name__ == "__main__":
    main()
