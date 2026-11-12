import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { agentAuthoring } from "@/test-utils/authoring";
import type { AgentSpec } from "@/types/agents";
import { Perm, type Permission } from "@/types/permissions";
import { AssistantStrip } from "./assistant-strip";
import { ImproveContextButton } from "./improve-skill-button";

const held = vi.hoisted(() => ({ permissions: new Set<string>() }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (permission: Permission) => held.permissions.has(permission) }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  // The suggestions keep their tab in `?suggestions=`.
  useSearchParams: () => new URLSearchParams(),
}));
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
      decideIdea: idle,
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
    useContextAuthoring: () => ({
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
      <ImproveContextButton contextId="context-1" />
    </>,
  );
}

beforeEach(() => {
  held.permissions = new Set();
});

describe("the assistant's controls, by permission", () => {
  it("hides generated suggestions from an editor who may not read runs", () => {
    held.permissions = new Set([Perm.agentsEdit, Perm.skillsEdit]);
    surfaces();
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dismiss all" })).toBeNull();
    for (const name of [
      "Improve",
      "Verify my edits",
      "Check with evals",
      "Improve with the assistant",
    ]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });

  it("offers suggestion checks to a reader of runs without duplicating builder actions", () => {
    held.permissions = new Set([Perm.agentsEdit, Perm.skillsEdit, Perm.runsView]);
    surfaces();
    expect(screen.queryByRole("button", { name: "Improve agent-1" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Verify my edits" })).toBeNull();
    expect(screen.getByRole("button", { name: "Check with evals" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Improve with the assistant" })).toBeInTheDocument();
  });

  it("offers no check on the agent to a reader of runs who may not run its draft on a dataset", () => {
    held.permissions = new Set([Perm.agentsEdit, Perm.skillsEdit, Perm.runsView]);
    surfaces({ canCheck: false });
    expect(screen.queryByRole("button", { name: "Improve agent-1" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Check with evals" })).toBeNull();
  });
});
