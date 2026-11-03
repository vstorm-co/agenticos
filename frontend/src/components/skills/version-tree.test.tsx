import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { SkillAgentUsage } from "@/types/skill-versions";
import { VersionTree } from "./version-tree";

function onMain(name: string): SkillAgentUsage {
  return {
    agent: { id: name, name, slug: name.toLowerCase() },
    via_specialist: null,
    draft_only: false,
    binding: {
      state: "main",
      version: { id: "m25", number: 25, fork_id: null },
      fork: null,
      behind_main: 0,
    },
    agent_version: 1,
    environments: [],
    draft_differs: false,
    can_change: false,
    can_publish: false,
  };
}

describe("VersionTree", () => {
  it("folds the versions nobody uses and unfolds them on request", async () => {
    render(<VersionTree mainLatest={25} forks={[]} agents={[]} error={null} />);

    expect(screen.getByText("v25")).toBeInTheDocument();
    expect(screen.queryByText("v12")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "23 versions (v24–v2)" }));

    expect(screen.getByText("v12")).toBeInTheDocument();
  });

  it("names three agents at a version and counts the rest", () => {
    render(
      <VersionTree
        mainLatest={25}
        forks={[]}
        agents={["Ana", "Bo", "Cy", "Di", "Ed"].map(onMain)}
        error={null}
      />,
    );

    expect(screen.getByText("Cy")).toBeInTheDocument();
    expect(screen.queryByText("Di")).toBeNull();
    expect(screen.getByText("+2")).toHaveAttribute("title", "Di, Ed");
  });
});

describe("VersionTree's forks", () => {
  const fork = (latest: number | null) => ({
    id: "f1",
    skill_id: "s1",
    name: "Returns",
    base: { id: "m3", number: 3 },
    latest: latest === null ? null : { id: `r${latest}`, number: latest },
    changes: latest ?? 0,
    behind_main: 22,
    agents: 1,
    archive_candidate: false,
    archived_at: null,
    created_at: "2026-11-01T10:00:00Z",
  });
  const onFork = (latest: number | null): SkillAgentUsage => ({
    ...onMain("Refunds"),
    binding: {
      state: "fork",
      version: { id: "r", number: latest ?? 3, fork_id: "f1" },
      fork: { id: "f1", name: "Returns", base_number: 3, changes: latest ?? 0 },
      behind_main: 22,
    },
  });

  it("draws a fork off its base with its own versions and agents", () => {
    render(<VersionTree mainLatest={25} forks={[fork(2)]} agents={[onFork(2)]} error={null} />);

    expect(screen.getByText("Fork “Returns”")).toBeInTheDocument();
    expect(screen.getByText("2 changes · 22 behind main")).toBeInTheDocument();
    // Main's own v2 and the fork's v2, each on its line.
    expect(screen.getAllByText("v2")).toHaveLength(2);
    expect(screen.getByText("Refunds")).toBeInTheDocument();
  });

  it("holds the agents of a fork with no versions of its own on the branch", () => {
    render(
      <VersionTree mainLatest={25} forks={[fork(null)]} agents={[onFork(null)]} error={null} />,
    );

    expect(screen.getByText("no changes yet · 22 behind main")).toBeInTheDocument();
    expect(screen.getByText("Refunds")).toBeInTheDocument();
  });

  it("says when the agents cannot be read instead of drawing an empty tree", () => {
    render(<VersionTree mainLatest={25} forks={[]} agents={[]} error={new Error("offline")} />);

    expect(screen.getByText("offline")).toBeInTheDocument();
    expect(screen.queryByText("v25")).toBeNull();
  });
});
