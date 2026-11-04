/**
 * Where each box of a skill's version diagram sits, and the edges between them.
 *
 * Main runs left to right, oldest first, on the top lane. Each fork takes a lane of
 * its own below, starting one column right of the version it branched from, so its
 * edge leaves that version and runs down into the fork. A box holds every agent that
 * reads its version, so a lane is as tall as its tallest box.
 */

import type { TreeFork, TreeRow } from "@/lib/skill-version-tree";
import type { SkillAgentUsage, SkillFork } from "@/types/skill-versions";

export const NODE_WIDTH = 184;
const COLUMN = NODE_WIDTH + 56;
const HEAD = 44;
const AGENT_ROW = 30;
const LANE_GAP = 40;
/** Room above a fork's lane for its name. */
const LABEL = 28;

export type DiagramBox =
  | {
      kind: "version";
      key: string;
      /** The fork the version belongs to; null on main. */
      fork: SkillFork | null;
      number: number;
      latest: boolean;
      newest: number;
      agents: SkillAgentUsage[];
    }
  | { kind: "gap"; key: string; line: string; from: number; to: number; count: number }
  /** A fork with no version of its own: it serves its base, and holds its agents. */
  | { kind: "empty-fork"; key: string; fork: SkillFork; agents: SkillAgentUsage[] };

export interface Placed {
  box: DiagramBox;
  x: number;
  y: number;
  height: number;
}

export interface LaneLabel {
  fork: SkillFork;
  x: number;
  y: number;
}

export interface Diagram {
  boxes: Placed[];
  labels: LaneLabel[];
  /** SVG paths, keyed by the box they lead into. */
  edges: { key: string; path: string }[];
  width: number;
  height: number;
}

/** An agent served through several specialists is still one row in its box. */
const agentRows = (agents: SkillAgentUsage[]) =>
  new Set(agents.map((usage) => usage.agent.id)).size;

const heightOf = (box: DiagramBox) => {
  if (box.kind === "gap") return HEAD;
  const rows = agentRows(box.agents);
  return HEAD + rows * AGENT_ROW + (rows > 0 ? 8 : 0);
};

function lineBoxes(rows: TreeRow[], line: string, fork: SkillFork | null): DiagramBox[] {
  const newest = Math.max(...rows.map((row) => (row.kind === "gap" ? row.from : row.number)));
  return [...rows].reverse().map((row) =>
    row.kind === "gap"
      ? { ...row, key: `${line}:gap:${row.from}`, line }
      : {
          kind: "version",
          key: `${line}:${row.number}`,
          fork,
          number: row.number,
          latest: row.latest,
          newest,
          agents: row.agents,
        },
  );
}

/** The boxes of the tree's rows, laid out in columns and lanes. */
export function versionDiagram(rows: TreeRow[]): Diagram {
  const main = lineBoxes(rows, "main", null);
  const forks: { branch: TreeFork; base: number }[] = [];
  main.forEach((box, column) => {
    const row = rows[rows.length - 1 - column]!;
    if (box.kind === "version" && row.kind === "version") {
      for (const branch of row.forks) forks.push({ branch, base: column });
    }
  });

  const boxes: Placed[] = [];
  const labels: LaneLabel[] = [];
  const edges: Diagram["edges"] = [];
  const mainHeight = Math.max(...main.map(heightOf));
  main.forEach((box, column) => {
    boxes.push({ box, x: column * COLUMN, y: 0, height: heightOf(box) });
    if (column > 0) edges.push({ key: box.key, path: across(column - 1, column, 0) });
  });

  let top = mainHeight + LANE_GAP;
  for (const { branch, base } of forks) {
    const lane: DiagramBox[] =
      branch.rows.length > 0
        ? lineBoxes(branch.rows, branch.fork.id, branch.fork)
        : [
            {
              kind: "empty-fork",
              key: `${branch.fork.id}:empty`,
              fork: branch.fork,
              agents: branch.agents,
            },
          ];
    const y = top + LABEL;
    labels.push({ fork: branch.fork, x: (base + 1) * COLUMN, y: top });
    lane.forEach((box, index) => {
      const column = base + 1 + index;
      boxes.push({ box, x: column * COLUMN, y, height: heightOf(box) });
      edges.push({
        key: box.key,
        path: index === 0 ? down(base, column, y) : across(column - 1, column, y),
      });
    });
    top = y + Math.max(...lane.map(heightOf)) + LANE_GAP;
  }

  const right = Math.max(...boxes.map((placed) => placed.x)) + NODE_WIDTH;
  return { boxes, labels, edges, width: right, height: top - LANE_GAP };
}

/** From one box's head to the next one's, on the same lane. */
function across(from: number, to: number, y: number): string {
  const middle = y + HEAD / 2;
  return `M ${from * COLUMN + NODE_WIDTH} ${middle} L ${to * COLUMN} ${middle}`;
}

/** From the base version's head down into the fork's first box. */
function down(base: number, column: number, y: number): string {
  const startX = base * COLUMN + NODE_WIDTH;
  const startY = HEAD / 2;
  const endX = column * COLUMN;
  const endY = y + HEAD / 2;
  const bend = (endX - startX) / 2;
  return `M ${startX} ${startY} C ${startX + bend} ${startY}, ${startX + bend} ${endY}, ${endX} ${endY}`;
}
