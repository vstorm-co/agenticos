import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useOnboardingFlow } from "./use-onboarding-flow";
import { useOnboardingStore } from "@/stores";
import type { Permission } from "@/types/permissions";

// The pathname the arrived-signal reads; a test moves it to fake a navigation.
const nav = vi.hoisted(() => ({ pathname: "/dashboard" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));

// Mutable state the mocked hooks read, so a test can grow a list between renders.
const rig = vi.hoisted(() => ({
  agentTotal: 0,
  agentsLoading: false,
  profiles: [] as { secret_id: string | null; base_url?: string | null }[],
  modelsLoading: false,
  skillTotal: 0,
  skillLoading: false,
  kbs: [] as unknown[],
  connections: [] as unknown[],
  orgs: [] as unknown[] | undefined,
  can: (_permission: Permission): boolean => true,
}));

vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({ total: rig.agentTotal, isLoading: rig.agentsLoading }),
}));
vi.mock("@/hooks/use-model-providers", () => ({
  useModelProviders: () => ({ profiles: rig.profiles, isLoading: rig.modelsLoading }),
}));
vi.mock("@/hooks/use-skills", () => ({
  useSkills: () => ({ total: rig.skillTotal, isLoading: rig.skillLoading }),
}));
vi.mock("@/hooks/use-knowledge-bases", () => ({
  useKnowledgeBases: () => ({ kbs: rig.kbs, isLoading: false }),
}));
vi.mock("@/hooks/use-org-mcp-connections", () => ({
  useOrgMcpConnections: () => ({ connections: rig.connections, isLoading: false }),
}));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizationList: () => ({ data: rig.orgs, isLoading: false }),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: rig.can, isLoading: false, error: null }),
}));

// One flow given a second, signal-less step so the advance-not-finish branch and
// the no-signal branch are both reachable — the per-section flows are a single
// step. The registry itself is covered by `flows.test.ts`.
vi.mock("@/lib/onboarding/flows", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/onboarding/flows")>("@/lib/onboarding/flows");
  return {
    ...actual,
    FLOWS: {
      ...actual.FLOWS,
      "create-kb": {
        id: "create-kb",
        steps: [
          { id: "kb-a", target: "knowledge-new", signal: { kind: "created", resource: "kb" } },
          { id: "kb-b", target: "knowledge-attach" },
        ],
      },
    },
  };
});

beforeEach(() => {
  rig.agentTotal = 0;
  rig.agentsLoading = false;
  rig.profiles = [];
  rig.modelsLoading = false;
  rig.skillTotal = 0;
  rig.skillLoading = false;
  rig.kbs = [];
  rig.connections = [];
  rig.orgs = [];
  rig.can = () => true;
  nav.pathname = "/dashboard";
  useOnboardingStore.setState({
    isOpen: false,
    index: 0,
    mode: "tour",
    flowId: null,
    offer: null,
    choices: {},
    flowAgentId: null,
  });
});

describe("useOnboardingFlow", () => {
  it("is idle when no flow is running", () => {
    const { result } = renderHook(() => useOnboardingFlow());
    expect(result.current.isActive).toBe(false);
    expect(result.current.steps).toHaveLength(0);
    expect(result.current.step).toBeUndefined();
    expect(result.current.flowId).toBeNull();
  });

  it("runs the flow's steps the caller may perform", () => {
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-skill"));
    expect(result.current.isActive).toBe(true);
    expect(result.current.flowId).toBe("create-skill");
    expect(result.current.steps).toHaveLength(1);
    expect(result.current.step?.target).toBe("skills-new");
    expect(result.current.isLast).toBe(true);
  });

  it("is inactive when permissions filter every step away", () => {
    rig.can = () => false;
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-skill"));
    expect(result.current.steps).toHaveLength(0);
    expect(result.current.isActive).toBe(false);
  });

  it("meets the signal only once the resource list grows past where it began", () => {
    rig.skillTotal = 3; // three skills already exist
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-skill"));
    expect(result.current.signalMet).toBe(false);

    rig.skillTotal = 4; // the reader created one
    rerender();
    expect(result.current.signalMet).toBe(true);
  });

  it("does not mistake a list finishing its first load for a creation", () => {
    rig.skillLoading = true; // count unknown on the first frame
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-skill"));
    expect(result.current.signalMet).toBe(false);

    rig.skillLoading = false;
    rig.skillTotal = 3; // 0 → 3 as the list settles is not "created three"
    rerender();
    expect(result.current.signalMet).toBe(false);

    rig.skillTotal = 4;
    rerender();
    expect(result.current.signalMet).toBe(true);
  });

  it("advances through a multi-step flow and ends after the last", () => {
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-kb"));
    expect(result.current.index).toBe(0);

    act(() => result.current.next());
    expect(result.current.index).toBe(1);
    // The second step carries no signal, so it never auto-completes.
    expect(result.current.step?.target).toBe("knowledge-attach");
    expect(result.current.signalMet).toBe(false);
    expect(result.current.isLast).toBe(true);

    act(() => result.current.next());
    expect(useOnboardingStore.getState().isOpen).toBe(false);
  });

  it("finish ends the flow, and an unread org list counts as none", () => {
    // `data` undefined (a list that errored rather than loaded) reads as zero, not
    // a crash — the `?? 0` guard the count leans on.
    rig.orgs = undefined;
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-org"));
    expect(result.current.signalMet).toBe(false);
    act(() => result.current.finish());
    expect(useOnboardingStore.getState().isOpen).toBe(false);
  });

  it("advances the agent flow when an agent is created", () => {
    rig.agentTotal = 0;
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    expect(result.current.step?.id).toBe("flow-agent-create");
    expect(result.current.signalMet).toBe(false);

    rig.agentTotal = 1;
    rerender();
    expect(result.current.signalMet).toBe(true);
  });

  it("teaches adding a model when the org has none", () => {
    rig.profiles = [{ secret_id: null, base_url: null }]; // a profile with no usable key
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    const ids = result.current.steps.map((step) => step.id);
    expect(ids).toContain("flow-agent-model-add");
    expect(ids).not.toContain("flow-agent-model-pick");
  });

  it("points at the model picker when a keyed model already exists", () => {
    rig.profiles = [{ secret_id: "sec-1" }];
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    const ids = result.current.steps.map((step) => step.id);
    expect(ids).toContain("flow-agent-model-pick");
    expect(ids).not.toContain("flow-agent-model-add");
  });

  it("counts a self-hosted model with a base URL as runnable", () => {
    rig.profiles = [{ secret_id: null, base_url: "http://localhost:11434/v1" }];
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    expect(result.current.steps.map((step) => step.id)).toContain("flow-agent-model-pick");
  });

  it("assumes no model while the model list is still loading", () => {
    rig.modelsLoading = true;
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    // Nothing frozen yet, so the flow defaults to teaching how to add one.
    expect(result.current.steps.map((step) => step.id)).toContain("flow-agent-model-add");
  });

  it("opens the knowledge detour on yes and meets its arrived signals by page", () => {
    rig.kbs = []; // no knowledge base, so the fork is asked
    nav.pathname = "/rag";
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));

    // create(0), instructions(1), model-add(2), knowledge-ask(3) — no model, no KB.
    act(() => useOnboardingStore.getState().setIndex(3));
    expect(result.current.step?.id).toBe("flow-agent-knowledge-ask");

    // Yes records the fork and steps onto the detour it opens.
    act(() => result.current.answer("flow-agent-knowledge-ask", "yes"));
    expect(result.current.step?.id).toBe("flow-agent-knowledge-create");

    act(() => result.current.next());
    expect(result.current.step?.id).toBe("flow-agent-knowledge-return-nav");
    // On /rag still, so the "click Agents" step is not yet satisfied.
    expect(result.current.signalMet).toBe(false);
    nav.pathname = "/agents";
    rerender();
    expect(result.current.signalMet).toBe(true);

    act(() => result.current.next());
    expect(result.current.step?.id).toBe("flow-agent-knowledge-return-edit");
    // Any /agents/<id> is the builder, so opening the agent meets the arrival.
    expect(result.current.signalMet).toBe(false);
    nav.pathname = "/agents/agent-42";
    rerender();
    expect(result.current.signalMet).toBe(true);
  });

  it("exposes the captured agent id for a detour's return leg", () => {
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    expect(result.current.flowAgentId).toBeNull();
    act(() => result.current.setFlowAgentId("agent-42"));
    expect(result.current.flowAgentId).toBe("agent-42");
  });

  it("does not let the add-model step morph once the reader adds a model", () => {
    rig.profiles = []; // no models to start
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    act(() => useOnboardingStore.getState().setIndex(2)); // the model step
    expect(result.current.step?.id).toBe("flow-agent-model-add");

    rig.profiles = [{ secret_id: "sec-1" }]; // AddModel creates a new profile mid-flow
    rerender();
    // Frozen: still the add step, and its signal now fires rather than the step
    // turning into "pick a model" with nothing to advance it.
    expect(result.current.step?.id).toBe("flow-agent-model-add");
    expect(result.current.signalMet).toBe(true);
  });
});
