/**
 * A skill's version tree, laid out as the rows a reader scans from the newest down.
 *
 * Main versions run v1 to its latest without gaps, and each fork's versions do the
 * same within the fork. An agent sits where its default environment's version binds
 * it, and one bound only in its draft is on no line. A fork with no versions of its
 * own holds its agents on the branch itself, since it still serves its base.
 *
 * Only versions somebody would look for are drawn - each line's latest, v1, a version
 * an agent uses and a fork's base; every other stretch of two or more folds into one
 * row, so twenty versions nobody uses take one line.
 */

import type { SkillAgentUsage, SkillFork } from "@/types/skill-versions";

export interface TreeVersion {
  kind: "version";
  number: number;
  latest: boolean;
  agents: SkillAgentUsage[];
  /** The forks started from this main version, ordered by name. */
  forks: TreeFork[];
}

export interface TreeGap {
  kind: "gap";
  /** The newest and oldest folded versions, newest first as the rows run. */
  from: number;
  to: number;
  count: number;
}

export type TreeRow = TreeVersion | TreeGap;

export interface TreeFork {
  fork: SkillFork;
  /** Empty for a fork with no versions of its own yet. */
  rows: TreeRow[];
  agents: SkillAgentUsage[];
}

export interface TreeInput {
  mainLatest: number;
  forks: SkillFork[];
  agents: SkillAgentUsage[];
  /** Versions a reader unfolded, keyed by line: `main` or a fork's id. */
  expanded?: ReadonlyMap<string, ReadonlySet<number>>;
}

const NONE: ReadonlySet<number> = new Set();

export function versionTree({ mainLatest, forks, agents, expanded }: TreeInput): TreeRow[] {
  const atMain = new Map<number, SkillAgentUsage[]>();
  for (const usage of agents) {
    const binding = usage.binding;
    if (usage.draft_only || binding.state === "fork") continue;
    const number = binding.state === "main" ? mainLatest : binding.version.number;
    atMain.set(number, [...(atMain.get(number) ?? []), usage]);
  }
  const forksAt = new Map<number, TreeFork[]>();
  for (const fork of [...forks].sort((a, b) => a.name.localeCompare(b.name))) {
    const users = agents.filter((usage) => !usage.draft_only && usage.binding.fork?.id === fork.id);
    const latest = fork.latest?.number ?? 0;
    const rows = lineRows({
      latest,
      agentsAt: (number) => (number === latest ? users : []),
      unfolded: expanded?.get(fork.id) ?? NONE,
    });
    const branch = { fork, rows, agents: latest === 0 ? users : [] };
    forksAt.set(fork.base.number, [...(forksAt.get(fork.base.number) ?? []), branch]);
  }
  return lineRows({
    latest: mainLatest,
    agentsAt: (number) => atMain.get(number) ?? [],
    unfolded: expanded?.get("main") ?? NONE,
    forksAt: (number) => forksAt.get(number) ?? [],
  });
}

function lineRows({
  latest,
  agentsAt,
  unfolded,
  forksAt = () => [],
}: {
  latest: number;
  agentsAt: (number: number) => SkillAgentUsage[];
  unfolded: ReadonlySet<number>;
  forksAt?: (number: number) => TreeFork[];
}): TreeRow[] {
  const shown = (number: number) =>
    number === latest ||
    number === 1 ||
    unfolded.has(number) ||
    agentsAt(number).length > 0 ||
    forksAt(number).length > 0;
  const version = (number: number): TreeVersion => ({
    kind: "version",
    number,
    latest: number === latest,
    agents: agentsAt(number),
    forks: forksAt(number),
  });
  const rows: TreeRow[] = [];
  let number = latest;
  while (number >= 1) {
    let to = number;
    while (!shown(to) && to - 1 >= 1 && !shown(to - 1)) to -= 1;
    rows.push(
      to === number ? version(number) : { kind: "gap", from: number, to, count: number - to + 1 },
    );
    number = to - 1;
  }
  return rows;
}
