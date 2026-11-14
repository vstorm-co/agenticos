import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import type { ImprovementSkill, ImprovementSkills } from "@/types/improvement";
import { SkillHandoffs } from "./skill-handoffs";

const state = vi.hoisted(() => ({
  skills: undefined as ImprovementSkills | undefined,
  error: null as Error | null,
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovementSkills: () => ({ skills: state.skills, error: state.error }),
}));

const MAIN: ImprovementSkill = {
  skill_id: "s1",
  name: "refunds",
  binding: {
    state: "main",
    version: { id: "v4", number: 4, fork_id: null },
    fork: null,
    behind_main: 0,
  },
  agents_on_line: 5,
  hidden_agents: 2,
  problems: [
    {
      problem: "It says ninety days",
      evidence: [
        { run_id: "r1", quote: "You said 90 days" },
        { run_id: "r2", quote: null },
      ],
    },
  ],
  can_improve: true,
  update: null,
};

beforeEach(() => {
  state.skills = undefined;
  state.error = null;
});

it("hands a skill's problems to the skill's own Improve, on main", () => {
  state.skills = { items: [MAIN] };
  render(<SkillHandoffs session={SESSION} />);
  expect(screen.getByRole("heading", { name: "Belongs to a skill" })).toBeInTheDocument();
  expect(screen.getByText("Main · 5 agents")).toBeInTheDocument();
  expect(screen.getByText("2 more agents you cannot see use this skill.")).toBeInTheDocument();
  expect(screen.getByText("You said 90 days")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Improve refunds" })).toHaveAttribute(
    "href",
    `/skills/s1/improve/new?from_run=${SESSION.id}`,
  );
});

it("hands a forked agent's problems to its fork, and a reader who cannot edit asks", () => {
  state.skills = {
    items: [
      {
        ...MAIN,
        binding: {
          state: "fork",
          version: { id: "f2", number: 2, fork_id: "f" },
          fork: { id: "f", name: "Returns", base_number: 3, changes: 1 },
          behind_main: 0,
        },
        agents_on_line: 1,
        hidden_agents: 0,
      },
      { ...MAIN, skill_id: "s2", name: "shipping", can_improve: false },
    ],
  };
  render(<SkillHandoffs session={SESSION} />);
  expect(screen.getByText('Fork "Returns" · 1 agent')).toBeInTheDocument();
  expect(screen.getByRole("link", { name: 'Improve refunds, fork "Returns"' })).toHaveAttribute(
    "href",
    `/skills/s1/improve/new?from_run=${SESSION.id}`,
  );
  expect(screen.getByText("Ask someone who can edit shipping to improve it.")).toBeVisible();
  expect(screen.queryByRole("link", { name: "Improve shipping" })).not.toBeInTheDocument();
});

it("offers a pinned agent the newer version and a fork the catch-up", () => {
  const behind = (state: "pinned" | "fork") => ({
    ...MAIN.binding!,
    state,
    behind_main: state === "pinned" ? 3 : 1,
  });
  state.skills = {
    items: [
      {
        ...MAIN,
        problems: [],
        binding: behind("pinned"),
        update: { kind: "update_pinned", to_version: 4 },
      },
      {
        ...MAIN,
        skill_id: "s2",
        name: "shipping",
        problems: [],
        binding: behind("fork"),
        update: { kind: "catch_up_fork", to_version: 4 },
      },
    ],
  };
  render(<SkillHandoffs session={SESSION} />);
  expect(screen.getByText("This agent is 3 versions behind main.")).toBeVisible();
  expect(screen.getByRole("link", { name: "Update to v4" })).toHaveAttribute("href", "/skills/s1");
  expect(screen.getByRole("link", { name: "Catch up the fork" })).toHaveAttribute(
    "href",
    "/skills/s2",
  );
});

it("shows nothing when no skill has a problem or a newer version, or a skill is unseen", () => {
  state.skills = {
    items: [
      { ...MAIN, problems: [] },
      { ...MAIN, skill_id: "s3", binding: null, agents_on_line: null, problems: [] },
    ],
  };
  const { container } = render(<SkillHandoffs session={SESSION} />);
  expect(container).toBeEmptyDOMElement();
  state.skills = undefined;
  render(<SkillHandoffs session={SESSION} />);
  expect(screen.queryByRole("heading")).not.toBeInTheDocument();
});

it("names an unseen skill's problems without its line", () => {
  state.skills = { items: [{ ...MAIN, binding: null, agents_on_line: null }] };
  render(<SkillHandoffs session={SESSION} />);
  expect(screen.getByRole("heading", { name: "refunds" })).toBeInTheDocument();
  expect(screen.queryByText(/Main ·/)).not.toBeInTheDocument();
});

it("says the skills could not be read instead of hiding the section", () => {
  state.error = new Error("Network down");
  render(<SkillHandoffs session={SESSION} />);
  expect(screen.getByRole("heading", { name: "Belongs to a skill" })).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Network down");
  expect(screen.queryByText(/is shared by other agents/)).not.toBeInTheDocument();
});
