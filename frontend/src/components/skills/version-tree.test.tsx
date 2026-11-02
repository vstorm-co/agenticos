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
  };
}

describe("VersionTree", () => {
  it("folds the versions nobody uses and unfolds them on request", async () => {
    render(<VersionTree mainLatest={25} forks={[]} agents={[]} />);

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
      />,
    );

    expect(screen.getByText("Cy")).toBeInTheDocument();
    expect(screen.queryByText("Di")).toBeNull();
    expect(screen.getByText("+2")).toHaveAttribute("title", "Di, Ed");
  });
});
