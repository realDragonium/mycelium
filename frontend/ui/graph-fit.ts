// Camera framing shared by the statement graph and the entity map.

export interface Point { x: number; y: number }
export interface Camera { pan: Point; zoom: number }

const PAD = 48;

// The pan and zoom that centre `points` in a width × height canvas with a
// margin, or null when there is nothing to frame or no canvas yet.
export function fitCamera(points: readonly Point[], width: number, height: number, minZoom: number, maxZoom: number): Camera | null {
  if (!points.length || width <= 0 || height <= 0) return null;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of points) {
    minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
  }
  const fit = Math.min(Math.max(1, width - PAD * 2) / Math.max(1, maxX - minX), Math.max(1, height - PAD * 2) / Math.max(1, maxY - minY));
  const zoom = Math.max(minZoom, Math.min(maxZoom, fit));
  return { zoom, pan: { x: width / 2 - ((minX + maxX) / 2) * zoom, y: height / 2 - ((minY + maxY) / 2) * zoom } };
}

// The node and everything it links to, so a focus change frames the
// neighbourhood the side panel describes rather than one dot.
export function neighbourhood<N extends { id: string }>(id: string, nodes: readonly N[], edges: readonly { src: N; tgt: N }[]): N[] {
  const ids = new Set([id]);
  for (const e of edges) {
    if (e.src.id === id) ids.add(e.tgt.id);
    if (e.tgt.id === id) ids.add(e.src.id);
  }
  return nodes.filter(n => ids.has(n.id));
}
