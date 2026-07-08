"""Render the entity graph to a PNG from the bake output + substrate.

Companion to `build_entity_layout.py`. That script computes positions
and writes the JSON the UI consumes; this one rasterizes the same
data into a static image — useful for embedding in slides, docs, an
incident write-up, or anywhere a live `/ui/#/entities` view isn't
practical.

Usage:
  uv run python scripts/render_entity_graph.py \\
      --db /var/lib/mycelium/mycelium.db \\
      --positions src/mycelium/ui/data/entity-positions.json \\
      --output entity-graph.png \\
      [--theme dark|light] [--top-labels 60]

Defaults match the project layout for a local checkout, so a bare
`uv run python scripts/render_entity_graph.py` works without args.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / ".mycelium" / "mycelium.db"
DEFAULT_POSITIONS = (
    REPO_ROOT / "src" / "mycelium" / "ui" / "data" / "entity-positions.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "entity-graph.png"


THEMES = {
    "dark": {
        "bg": "#0b0b0c",
        "edge": "#3f3f46",
        "edge_alpha": 0.35,
        "label": "#e4e4e7",
        # 12-stop palette covering the typical n_components range
        "palette": [
            "#f87171",
            "#fbbf24",
            "#a3e635",
            "#4ade80",
            "#22d3ee",
            "#60a5fa",
            "#a78bfa",
            "#f472b6",
            "#fb923c",
            "#facc15",
            "#34d399",
            "#818cf8",
        ],
    },
    "light": {
        "bg": "#ffffff",
        "edge": "#94a3b8",
        "edge_alpha": 0.4,
        "label": "#0f172a",
        "palette": [
            "#dc2626",
            "#d97706",
            "#65a30d",
            "#16a34a",
            "#0891b2",
            "#2563eb",
            "#7c3aed",
            "#db2777",
            "#ea580c",
            "#ca8a04",
            "#059669",
            "#4f46e5",
        ],
    },
}


def render(
    db: Path,
    positions: Path,
    output: Path,
    theme: str = "dark",
    top_labels: int = 60,
) -> dict:
    pos_doc = json.loads(positions.read_text())
    nodes = pos_doc["nodes"]
    nodes_by_id = {n["id"]: n for n in nodes}

    conn = sqlite3.connect(str(db))
    links = conn.execute(
        "SELECT from_entity_id, to_entity_id FROM entity_links"
    ).fetchall()
    conn.close()

    style = THEMES[theme]
    fig, ax = plt.subplots(figsize=(14, 14), facecolor=style["bg"])
    ax.set_facecolor(style["bg"])
    ax.set_aspect("equal")
    ax.set_axis_off()

    # Edges as a single LineCollection — orders of magnitude faster
    # than one ax.plot per edge when there are hundreds of them.
    segments = []
    for a, b in links:
        na, nb = nodes_by_id.get(a), nodes_by_id.get(b)
        if na is None or nb is None:
            continue
        segments.append([(na["x"], na["y"]), (nb["x"], nb["y"])])
    if segments:
        edge_collection = LineCollection(
            segments,
            colors=style["edge"],
            linewidths=0.6,
            alpha=style["edge_alpha"],
            zorder=1,
        )
        ax.add_collection(edge_collection)

    # Nodes — one scatter call per component so legend / color binding
    # is consistent. Size scales with degree; clamp to keep hubs from
    # eating their neighbors.
    palette = style["palette"]
    by_component: dict[int, list[dict]] = {}
    for n in nodes:
        by_component.setdefault(n["component"], []).append(n)

    for comp_id, comp_nodes in by_component.items():
        color = palette[comp_id % len(palette)]
        sizes = [max(8, min(220, n["degree"] * 14)) for n in comp_nodes]
        ax.scatter(
            [n["x"] for n in comp_nodes],
            [n["y"] for n in comp_nodes],
            s=sizes,
            c=color,
            alpha=0.9,
            linewidths=0,
            zorder=2,
        )

    # Labels for top-degree nodes only — annotating every node makes
    # the image unreadable.
    top = sorted(nodes, key=lambda n: -n["degree"])[:top_labels]
    for n in top:
        ax.annotate(
            (n["name"] or "")[:36],
            xy=(n["x"], n["y"]),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=7,
            color=style["label"],
            zorder=3,
        )

    # Tight crop with a small margin, then save.
    ax.autoscale_view()
    fig.tight_layout(pad=0.5)
    fig.savefig(output, dpi=150, facecolor=style["bg"])
    plt.close(fig)

    return {
        "nodes": len(nodes),
        "edges": len(segments),
        "components": pos_doc.get("n_components"),
        "output": str(output),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--positions", type=Path, default=DEFAULT_POSITIONS)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--theme", choices=list(THEMES.keys()), default="dark")
    ap.add_argument("--top-labels", type=int, default=60)
    args = ap.parse_args()

    if not args.positions.exists():
        print(f"positions file not found: {args.positions}", file=sys.stderr)
        print("hint: run scripts/build_entity_layout.py first", file=sys.stderr)
        sys.exit(1)
    if not args.db.exists():
        print(f"db not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    stats = render(
        db=args.db,
        positions=args.positions,
        output=args.output,
        theme=args.theme,
        top_labels=args.top_labels,
    )
    print(
        f"wrote {stats['output']}  "
        f"({stats['nodes']} nodes, {stats['edges']} edges, "
        f"{stats['components']} components)"
    )


if __name__ == "__main__":
    main()
