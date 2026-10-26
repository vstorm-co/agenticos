import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/agents/improve-link", () => ({
  ImproveButton: ({ agentId }: { agentId: string }) => <button>Improve {agentId}</button>,
}));
import { agentAuthoring } from "@/test-utils/authoring";
import type { AgentSpec } from "@/types/agents";
import { Perm, type Permission } from "@/types/permissions";
import { AssistantStrip } from "./assistant-strip";
import { ImproveSkillButton } from "./improve-skill-button";
import { SkillCheckButton } from "./skill-check-button";

const held = vi.hoisted(() => ({ permissions: new Set<string>() }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (permission: Permission) => held.permissions.has(permission) }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/hooks", () => ({ useDraftBase: () => ({ base: { spec: { name: "Old" } } }) }));
vi.mock("@/hooks/use-organizations", () => ({
  useAiAssistance: () => ({ orgId: "org-1", enabled: true }),
}));
vi.mock("@/hooks/use-authoring", () => {
  const idle = { mutateAsync: vi.fn(), mutate: vi.fn(), isPending: false };
  return {
    useAgentAuthoring: () => ({
      authoring: agentAuthoring(),
      isLoading: false,
      error: null,
      estimate: idle,
      start: idle,
      decide: idle,
      dismissAll: idle,
      checkEstimate: idle,
      check: idle,
    }),
    useSkillAuthoring: () => ({
      latest: null,
      estimate: idle,
      start: idle,
      checkEstimate: idle,
      check: idle,
    }),
  };
});

const DRAFT = { name: "Clerk", instructions: "Be brief." } as AgentSpec;

function surfaces({ canCheck = true } = {}) {
  render(
    <>
      <AssistantStrip
        agentId="agent-1"
        storedDraft={DRAFT}
        canCheck={canCheck}
        persist={vi.fn()}
        onDraft={vi.fn()}
      />
      <ImproveSkillButton skillId="skill-1" />
      <SkillCheckButton skillId="skill-1" proposalId="change-1" />
    </>,
  );
}

beforeEach(() => {
  held.permissions = new Set();
});

describe("the assistant's controls, by permission", () => {
  it("lets a member who may edit but not read runs decide what waits, and ask for nothing", () => {
    held.permissions = new Set([Perm.agentsEdit, Perm.skillsEdit]);
    surfaces();
    expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss all" })).toBeInTheDocument();
    for (const name of [
      "Improve",
      "Verify my edits",
      "Check with evals",
      "Improve with the assistant",
    ]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });

  it("offers asking, verifying and checking to a reader of runs", () => {
    held.permissions = new Set([Perm.agentsEdit, Perm.skillsEdit, Perm.runsView]);
    surfaces();
    expect(screen.getByRole("button", { name: "Improve agent-1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Verify my edits" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Check with evals" })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Improve with the assistant" })).toBeInTheDocument();
  });

  it("offers no check on the agent to a reader of runs who may not run its draft on a dataset", () => {
    held.permissions = new Set([Perm.agentsEdit, Perm.skillsEdit, Perm.runsView]);
    surfaces({ canCheck: false });
    expect(screen.getByRole("button", { name: "Improve agent-1" })).toBeInTheDocument();
    // The one left is the skill change's, which checks on an agent of its own.
    expect(screen.getAllByRole("button", { name: "Check with evals" })).toHaveLength(1);
  });
});
