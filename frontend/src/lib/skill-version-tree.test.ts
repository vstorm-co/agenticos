import { describe, expect, it } from "vitest";

import { versionTree, type TreeRow, type TreeVersion } from "./skill-version-tree";
import type { SkillAgentUsage, SkillBindingState, SkillFork } from "@/types/skill-versions";

function agent(
  name: string,
  state: SkillBindingState,
  number: number,
  fork: SkillFork | null = null,
  { draftOnly = false }: { draftOnly?: boolean } = {},
): SkillAgentUsage {
  return {
    agent: { id: name, name, slug: name },
    via_specialist: null,
    draft_only: draftOnly,
    binding: {
      state,
      version: { id: `${fork?.id ?? "main"}-${number}`, number, fork_id: fork?.id ?? null },
      fork: fork && {
        id: fork.id,
        name: fork.name,
        base_number: fork.base.number,
        changes: fork.changes,
      },
      behind_main: 0,
    },
    agent_version: draftOnly ? null : 1,
    environments: [],
    draft_differs: false,
    can_change: true,
    can_publish: true,
  };
}

function fork(id: string, name: string, base: number, latest: number): SkillFork {
  return {
    id,
    skill_id: "skill",
    name,
    base: { id: `main-${base}`, number: base },
    latest: latest === 0 ? null : { id: `${id}-${latest}`, number: latest },
    changes: latest,
    behind_main: 0,
    agents: 0,
    archive_candidate: false,
    archived_at: null,
    created_at: "2026-11-02T10:00:00Z",
  };
}

/** The rows as a reader scans them: `v12`, `v11–v3` for a fold. */
function shape(rows: TreeRow[]): string[] {
  return rows.map((row) => (row.kind === "gap" ? `v${row.from}–v${row.to}` : `v${row.number}`));
}

function at(rows: TreeRow[], number: number): TreeVersion {
  const row = rows.find((one) => one.kind === "version" && one.number === number);
  if (row?.kind !== "version") throw new Error(`v${number} is not drawn`);
  return row;
}

describe("versionTree", () => {
  it("folds twenty versions nobody uses into one row between the latest and v1", () => {
    const rows = versionTree({ mainLatest: 25, forks: [], agents: [] });

    expect(shape(rows)).toEqual(["v25", "v24–v2", "v1"]);
    expect(rows[1]).toMatchObject({ kind: "gap", count: 23 });
  });

  it("puts agents following main at the latest version and pinned ones where they stay", () => {
    const rows = versionTree({
      mainLatest: 12,
      forks: [],
      agents: [agent("Support", "main", 12), agent("HR", "pinned", 9)],
    });

    expect(shape(rows)).toEqual(["v12", "v11–v10", "v9", "v8–v2", "v1"]);
    expect(at(rows, 12).agents.map((one) => one.agent.name)).toEqual(["Support"]);
    expect(at(rows, 9).agents.map((one) => one.agent.name)).toEqual(["HR"]);
  });

  it("draws a lone unused version rather than folding it into a row of one", () => {
    const rows = versionTree({
      mainLatest: 4,
      forks: [],
      agents: [agent("HR", "pinned", 2)],
    });

    expect(shape(rows)).toEqual(["v4", "v3", "v2", "v1"]);
  });

  it("branches each fork from its base, siblings from one base ordered by name", () => {
    const returns = fork("f1", "Returns", 7, 2);
    const exchanges = fork("f2", "Exchanges", 7, 1);
    const vip = fork("f3", "VIP", 3, 1);
    const rows = versionTree({
      mainLatest: 13,
      forks: [returns, exchanges, vip],
      agents: [agent("Refund desk", "fork", 2, returns)],
    });

    expect(shape(rows)).toEqual(["v13", "v12–v8", "v7", "v6–v4", "v3", "v2", "v1"]);
    expect(at(rows, 7).forks.map((one) => one.fork.name)).toEqual(["Exchanges", "Returns"]);
    expect(at(rows, 3).forks.map((one) => one.fork.name)).toEqual(["VIP"]);
    const branch = at(rows, 7).forks[1]!;
    expect(shape(branch.rows)).toEqual(["v2", "v1"]);
    expect(at(branch.rows, 2).agents.map((one) => one.agent.name)).toEqual(["Refund desk"]);
  });

  it("keeps fork agents off the main line", () => {
    const returns = fork("f1", "Returns", 2, 1);
    const rows = versionTree({
      mainLatest: 3,
      forks: [returns],
      agents: [agent("Refund desk", "fork", 1, returns)],
    });

    expect(rows.flatMap((row) => (row.kind === "version" ? row.agents : []))).toEqual([]);
  });

  it("folds a long fork the same way as main", () => {
    const long = fork("f1", "Returns", 1, 30);
    const rows = versionTree({ mainLatest: 1, forks: [long], agents: [] });

    expect(shape(at(rows, 1).forks[0]!.rows)).toEqual(["v30", "v29–v2", "v1"]);
  });

  it("draws the versions a reader unfolded, per line", () => {
    const returns = fork("f1", "Returns", 1, 6);
    const rows = versionTree({
      mainLatest: 10,
      forks: [returns],
      agents: [],
      expanded: new Map([
        ["main", new Set([9, 8, 7])],
        ["f1", new Set([3])],
      ]),
    });

    expect(shape(rows)).toEqual(["v10", "v9", "v8", "v7", "v6–v2", "v1"]);
    expect(shape(at(rows, 1).forks[0]!.rows)).toEqual(["v6", "v5–v4", "v3", "v2", "v1"]);
  });

  it("holds the agents of a fork with no versions of its own on the branch", () => {
    const fresh = fork("f1", "Returns", 2, 0);
    const rows = versionTree({
      mainLatest: 3,
      forks: [fresh],
      agents: [agent("Refund desk", "fork", 2, fresh)],
    });

    const branch = at(rows, 2).forks[0]!;
    expect(branch.rows).toEqual([]);
    expect(branch.agents.map((one) => one.agent.name)).toEqual(["Refund desk"]);
  });

  it("leaves out an agent that binds the skill only in its draft", () => {
    const rows = versionTree({
      mainLatest: 2,
      forks: [],
      agents: [agent("Draft", "pinned", 1, null, { draftOnly: true })],
    });

    expect(rows.flatMap((row) => (row.kind === "version" ? row.agents : []))).toEqual([]);
  });

  it("draws a skill with one version as one row", () => {
    expect(shape(versionTree({ mainLatest: 1, forks: [], agents: [] }))).toEqual(["v1"]);
  });
});
