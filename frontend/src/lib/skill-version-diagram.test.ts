import { describe, expect, it } from "vitest";

import { versionDiagram } from "./skill-version-diagram";
import { versionTree } from "./skill-version-tree";
import type { SkillAgentUsage, SkillFork } from "@/types/skill-versions";

const fork = (id: string, base: number, latest: number | null): SkillFork => ({
  id,
  skill_id: "s1",
  name: id,
  base: { id: `m${base}`, number: base },
  started_from: { id: `m${base}`, number: base },
  latest: latest === null ? null : { id: `${id}${latest}`, number: latest },
  changes: latest ?? 0,
  behind_main: 0,
  agents: 0,
  archive_candidate: false,
  archived_at: null,
  created_at: "2026-11-01T10:00:00Z",
});

const onMain = (name: string, viaSpecialist: string | null = null) =>
  ({
    agent: { id: name, name, slug: name },
    via_specialist: viaSpecialist,
    draft_only: false,
    binding: { state: "main", version: { id: "m3", number: 3, fork_id: null }, fork: null },
  }) as SkillAgentUsage;

describe("versionDiagram", () => {
  it("runs main left to right, oldest first, joined box to box", () => {
    const diagram = versionDiagram(versionTree({ mainLatest: 3, forks: [], agents: [] }));
    const main = diagram.boxes.map(({ box, x, y }) => [box.kind === "version" && box.number, x, y]);
    expect(main).toEqual([
      [1, 0, 0],
      [2, 240, 0],
      [3, 480, 0],
    ]);
    expect(diagram.edges.map((edge) => edge.key)).toEqual(["main:2", "main:3"]);
    expect(diagram.edges[0]!.path).toBe("M 184 22 L 240 22");
    expect(diagram.width).toBe(664);
    expect(diagram.height).toBe(44);
  });

  it("gives each fork a lane below, starting right of its base and curving down from it", () => {
    const diagram = versionDiagram(
      versionTree({
        mainLatest: 3,
        forks: [fork("a", 2, 2), fork("b", 2, null)],
        agents: [onMain("Ana"), onMain("Ana", "Helper"), onMain("Bo")],
      }),
    );
    const newest = diagram.boxes.find((placed) => placed.box.key === "main:3")!;
    // Two agents, Ana listed once for both of the ways she reads it.
    expect(newest.height).toBe(44 + 2 * 30 + 8);
    const lanes = diagram.boxes
      .filter((placed) => placed.y > 0)
      .map(({ box, x, y }) => [box.key, x, y]);
    expect(lanes).toEqual([
      ["a:1", 480, 180],
      ["a:2", 720, 180],
      ["b:empty", 480, 292],
    ]);
    expect(diagram.labels.map(({ fork: line, x, y }) => [line.id, x, y])).toEqual([
      ["a", 480, 152],
      ["b", 480, 264],
    ]);
    expect(diagram.edges.find((edge) => edge.key === "a:1")!.path).toBe(
      "M 424 22 C 452 22, 452 202, 480 202",
    );
    expect(diagram.height).toBe(336);
  });

  it("draws a folded stretch as one box of its own", () => {
    const diagram = versionDiagram(versionTree({ mainLatest: 9, forks: [], agents: [] }));
    expect(diagram.boxes.map(({ box }) => box.kind)).toEqual(["version", "gap", "version"]);
  });
});
