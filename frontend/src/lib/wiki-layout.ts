import type { WikiGraph, WikiPage } from "./wiki-graph";

export interface WikiPoint {
  x: number;
  y: number;
}

export interface WikiPosition extends WikiPoint {
  page: WikiPage;
}

interface Particle extends WikiPosition {
  fx: number;
  fy: number;
}

/** A bounded, deterministic force layout; no animation loop or physics dependency. */
export function layoutWiki(graph: WikiGraph): Map<string, WikiPosition> {
  const points = new Map<string, Particle>(
    graph.pages.map((page, index) => {
      const angle = index * 2.399963229728653;
      const radius = 28 * Math.sqrt(index + 1);
      return [
        page.path,
        {
          x: 500 + Math.cos(angle) * radius,
          y: 350 + Math.sin(angle) * radius,
          fx: 0,
          fy: 0,
          page,
        },
      ];
    }),
  );
  const entries = [...points.values()];
  for (let step = 0; step < 240; step++) {
    for (const point of entries) {
      point.fx = (500 - point.x) * 0.004;
      point.fy = (350 - point.y) * 0.004;
    }
    for (const [index, a] of entries.entries()) {
      for (const b of entries.slice(index + 1)) {
        const dx = a.x - b.x,
          dy = a.y - b.y;
        const distance = Math.max(16, Math.hypot(dx, dy));
        const strength = 220 / (distance * distance);
        a.fx += dx * strength;
        a.fy += dy * strength;
        b.fx -= dx * strength;
        b.fy -= dy * strength;
      }
    }
    for (const edge of graph.edges) {
      const a = points.get(edge.source),
        b = points.get(edge.target);
      if (!a || !b) continue;
      const dx = b.x - a.x,
        dy = b.y - a.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const strength = ((distance - 55) * 0.045) / distance;
      a.fx += dx * strength;
      a.fy += dy * strength;
      b.fx -= dx * strength;
      b.fy -= dy * strength;
    }
    for (const point of entries) {
      point.x = point.x + Math.max(-10, Math.min(10, point.fx));
      point.y = point.y + Math.max(-10, Math.min(10, point.fy));
    }
  }
  return new Map([...points].map(([path, { x, y, page }]) => [path, { x, y, page }]));
}
