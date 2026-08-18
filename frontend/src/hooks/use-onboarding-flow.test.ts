import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useOnboardingFlow } from "./use-onboarding-flow";
import { useOnboardingStore } from "@/stores";
import { useAgentSelectionStore } from "@/stores/agent-selection-store";
import { useChatStore } from "@/stores/chat-store";
import { useConversationStore } from "@/stores/conversation-store";
import { Perm, type Permission } from "@/types/permissions";

// The pathname the arrived-signal reads; a test moves it to fake a navigation.
const nav = vi.hoisted(() => ({ pathname: "/dashboard" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));

// Mutable state the mocked hooks read, so a test can grow a list between renders.
const rig = vi.hoisted(() => ({
  agentTotal: 0,
  agentsLoading: false,
  agentsList: [] as { id?: string; status: string }[],
  agentDetail: null as { status: string; draft_spec: { model_profile_id: string | null } } | null,
  profiles: [] as { secret_id: string | null; base_url?: string | null }[],
  modelsLoading: false,
  skillTotal: 0,
  skillLoading: false,
  skillFetching: false,
  kbs: [] as unknown[],
  connections: [] as unknown[],
  personalConnections: [] as unknown[],
  mcpLoading: false,
  orgs: [] as unknown[] | undefined,
  can: (_permission: Permission): boolean => true,
}));

vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({
    agents: rig.agentsList,
    total: rig.agentTotal,
    isLoading: rig.agentsLoading,
    isFetching: rig.agentsLoading,
  }),
  // Disabled when no id is captured, mirroring `enabled: !!agentId` in the real hook.
  useAgent: (id: string | null) => ({ agent: id ? rig.agentDetail : undefined }),
}));
vi.mock("@/hooks/use-model-providers", () => ({
  useModelProviders: () => ({
    profiles: rig.profiles,
    isLoading: rig.modelsLoading,
    isFetching: rig.modelsLoading,
  }),
}));
vi.mock("@/hooks/use-skills", () => ({
  useSkills: () => ({
    total: rig.skillTotal,
    isLoading: rig.skillLoading,
    isFetching: rig.skillLoading || rig.skillFetching,
  }),
}));
vi.mock("@/hooks/use-knowledge-bases", () => ({
  useKnowledgeBases: () => ({ kbs: rig.kbs, isLoading: false, isFetching: false }),
}));
vi.mock("@/hooks/use-org-mcp-connections", () => ({
  useOrgMcpConnections: () => ({
    connections: rig.connections,
    isLoading: rig.mcpLoading,
    isFetching: rig.mcpLoading,
  }),
}));
vi.mock("@/hooks/use-mcp-connections", () => ({
  useMcpConnections: () => ({
    connections: rig.personalConnections,
    isLoading: false,
    isFetching: false,
  }),
}));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizationList: () => ({ data: rig.orgs, isLoading: false, isFetching: false }),
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
  rig.agentsList = [];
  rig.agentDetail = null;
  rig.profiles = [];
  rig.modelsLoading = false;
  rig.skillTotal = 0;
  rig.skillLoading = false;
  rig.skillFetching = false;
  rig.kbs = [];
  rig.connections = [];
  rig.personalConnections = [];
  rig.mcpLoading = false;
  rig.orgs = [];
  rig.can = () => true;
  nav.pathname = "/dashboard";
  useAgentSelectionStore.setState({ selectedAgentId: null });
  useChatStore.setState({ messages: [] });
  useConversationStore.setState({ currentConversationId: null, currentMessages: [] });
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
    // The opener plus the walk through the dialog's fields.
    expect(result.current.steps.length).toBeGreaterThan(1);
    expect(result.current.step?.target).toBe("skills-new");
    expect(result.current.isLast).toBe(false);
  });

  it("is inactive when permissions filter every step away", () => {
    rig.can = () => false;
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-skill"));
    expect(result.current.steps).toHaveLength(0);
    expect(result.current.isActive).toBe(false);
  });

  it("stays inactive until the org snapshot has settled, so no fork morphs", () => {
    // One input still loading, so `liveState` is null and the state cannot freeze.
    // The steps below are computed from the empty-org default; activating on them
    // would flash a fork built for an org that may not be empty and swap it away
    // the moment the lists land, so `isActive` waits for the snapshot.
    rig.agentsLoading = true;
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    expect(result.current.isActive).toBe(false);

    rig.agentsLoading = false;
    rerender();
    expect(result.current.isActive).toBe(true);
  });

  it("meets the signal only once the resource list grows past where it began", () => {
    rig.skillTotal = 3; // three skills already exist
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-skill"));
    // The `created` signal lives on the dialog's own Create step.
    const createAt = result.current.steps.findIndex((s) => s.id === "flow-skill-field-create");
    act(() => useOnboardingStore.getState().setIndex(createAt));
    expect(result.current.signalMet).toBe(false);

    rig.skillTotal = 4; // the reader created one
    rerender();
    expect(result.current.signalMet).toBe(true);
  });

  it("does not mistake a list finishing its first load for a creation", () => {
    rig.skillLoading = true; // count unknown on the first frame
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-skill"));
    const createAt = result.current.steps.findIndex((s) => s.id === "flow-skill-field-create");
    act(() => useOnboardingStore.getState().setIndex(createAt));
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

  it("ends the MCP connect step on a connection in either scope", () => {
    // "Connect" defaults to personal for a server the org already holds, so a walk
    // that only counted org connections would hang there. A personal one ends it.
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-mcp"));
    const connectAt = result.current.steps.findIndex((s) => s.id === "flow-mcp-field-connect");
    act(() => useOnboardingStore.getState().setIndex(connectAt));
    expect(result.current.step?.id).toBe("flow-mcp-field-connect");
    expect(result.current.signalMet).toBe(false);

    rig.personalConnections = [{}];
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

  it("points at where MCP servers attach when the org has a connection", () => {
    rig.connections = [{}]; // one connected server
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    const ids = result.current.steps.map((step) => step.id);
    expect(ids).toContain("flow-agent-mcp");
    expect(ids).not.toContain("flow-agent-mcp-ask");
  });

  it("asks to connect an MCP server, and assumes none while its list is still loading", () => {
    rig.mcpLoading = true; // count unknown, so the state has not settled
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    // Nothing frozen yet, so the flow defaults to asking to connect one.
    expect(result.current.steps.map((step) => step.id)).toContain("flow-agent-mcp-ask");

    // Once the list settles empty the fork stands: still asking, never pointing.
    rig.mcpLoading = false;
    rerender();
    const ids = result.current.steps.map((step) => step.id);
    expect(ids).toContain("flow-agent-mcp-ask");
    expect(ids).not.toContain("flow-agent-mcp");
  });

  it("tells a builder who cannot add a model that the org has none", () => {
    rig.profiles = []; // no runnable model
    rig.can = (permission) => permission !== "connections:manage";
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    const ids = result.current.steps.map((step) => step.id);
    expect(ids).toContain("flow-agent-model-none");
    expect(ids).not.toContain("flow-agent-model-add");
    expect(ids).not.toContain("flow-agent-model-pick");
  });

  it("asks the chat run to build an agent when only a draft exists", () => {
    // A draft agent has no version to run, so the chat cannot address it — the run
    // still opens with the build-one fork.
    rig.agentsList = [{ status: "draft" }];
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("explore-chat"));
    expect(result.current.step?.id).toBe("flow-chat-needs-agent");
  });

  it("goes straight into the chat tour when an agent is already published", () => {
    rig.agentsList = [{ status: "published" }];
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("explore-chat"));
    expect(result.current.step?.id).toBe("flow-chat-start");
  });

  it("assumes no published agent while the agent list is still loading", () => {
    rig.agentsLoading = true; // not settled, so the run assumes none and asks
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("explore-chat"));
    expect(result.current.step?.id).toBe("flow-chat-needs-agent");
  });

  it("exposes openFlow, for a fork that hands off to another flow", () => {
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("explore-chat"));
    act(() => result.current.openFlow("create-agent"));
    expect(result.current.flowId).toBe("create-agent");
  });

  it("gates the model step on the built agent's draft gaining a model", () => {
    rig.profiles = [{ secret_id: "s-1" }]; // org has a runnable model, so pick (not add) shows
    rig.agentDetail = { status: "draft", draft_spec: { model_profile_id: null } };
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    // No id captured yet: the draft cannot be read, so the gate holds shut.
    const modelAt = result.current.steps.findIndex((s) => s.id === "flow-agent-model-pick");
    act(() => useOnboardingStore.getState().setIndex(modelAt));
    expect(result.current.step?.id).toBe("flow-agent-model-pick");
    expect(result.current.signalMet).toBe(false);

    act(() => useOnboardingStore.getState().setFlowAgentId("a-mine"));
    rerender();
    expect(result.current.signalMet).toBe(false); // captured, but the draft has no model

    rig.agentDetail = { status: "draft", draft_spec: { model_profile_id: "m-1" } };
    rerender();
    expect(result.current.signalMet).toBe(true);
  });

  it("gates publish on the built agent gaining a published version", () => {
    rig.agentDetail = { status: "draft", draft_spec: { model_profile_id: "m-1" } };
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    const publishAt = result.current.steps.findIndex((s) => s.id === "flow-agent-publish");
    act(() => useOnboardingStore.getState().setIndex(publishAt));
    expect(result.current.step?.id).toBe("flow-agent-publish");
    expect(result.current.signalMet).toBe(false); // no agent captured yet

    act(() => useOnboardingStore.getState().setFlowAgentId("a-mine"));
    rerender();
    expect(result.current.signalMet).toBe(false); // captured, but still a draft

    rig.agentDetail = { status: "published", draft_spec: { model_profile_id: "m-1" } };
    rerender();
    expect(result.current.signalMet).toBe(true);
  });

  it("meets the selected signal only when the built agent is the one chat will address", () => {
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    act(() => useOnboardingStore.getState().setFlowAgentId("a-mine"));
    const pickAt = result.current.steps.findIndex((s) => s.id === "flow-agent-run-pick");
    act(() => useOnboardingStore.getState().setIndex(pickAt));
    expect(result.current.step?.id).toBe("flow-agent-run-pick");
    expect(result.current.signalMet).toBe(false);

    // Picking a different agent does not advance the step about this one.
    act(() => useAgentSelectionStore.setState({ selectedAgentId: "a-other" }));
    rerender();
    expect(result.current.signalMet).toBe(false);

    act(() => useAgentSelectionStore.setState({ selectedAgentId: "a-mine" }));
    rerender();
    expect(result.current.signalMet).toBe(true);
  });

  it("ends the run on a message sent while the step shows, not one from before", () => {
    // A transcript already on screen when the step begins must not read as the
    // send: the baseline captures its message count, and only growth past it counts.
    act(() => useChatStore.setState({ messages: [{ id: "m-0" } as never] }));
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    const sendAt = result.current.steps.findIndex((s) => s.id === "flow-agent-run-send");
    act(() => useOnboardingStore.getState().setIndex(sendAt));
    expect(result.current.step?.id).toBe("flow-agent-run-send");
    expect(result.current.isLast).toBe(true);
    expect(result.current.signalMet).toBe(false);

    // Sending appends optimistically; the count growing is the send.
    act(() => useChatStore.getState().addMessage({ id: "m-1" } as never));
    rerender();
    expect(result.current.signalMet).toBe(true);
  });

  it("reads the send from the transcript on screen, not the fetched one", () => {
    // A conversation created over the websocket never has its messages fetched, so
    // `useConversationStore.currentMessages` stays empty however many turns it
    // holds. Read from there, the fresh-agent path's first message moved nothing
    // and the walk sat on the composer while its run was already answering.
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    const sendAt = result.current.steps.findIndex((s) => s.id === "flow-agent-run-send");
    act(() => useOnboardingStore.getState().setIndex(sendAt));
    expect(result.current.signalMet).toBe(false);

    act(() => useConversationStore.setState({ currentMessages: [{ id: "fetched" } as never] }));
    rerender();
    expect(result.current.signalMet).toBe(false);

    act(() => useChatStore.getState().addMessage({ id: "sent" } as never));
    rerender();
    expect(result.current.signalMet).toBe(true);
  });

  it("ignores an answer when no flow is running", () => {
    // The whole state object is returned whether or not a flow is live, so `answer`
    // is callable with nothing to answer. Without a flow there is no step list to
    // resolve the choice against, and recording one would leave a stray fork in the
    // store for whichever flow opened next.
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => result.current.answer("flow-agent-knowledge-ask", "yes"));
    expect(useOnboardingStore.getState().choices).toEqual({});
    expect(useOnboardingStore.getState().index).toBe(0);
  });

  it("ends the walk when the fork it answers is the last step, rather than re-asking it", () => {
    // `answer` in the store records the choice and advances in one update, on the
    // claim that a question is never a flow's last step. It can be: create-agent's
    // tail is gated on `agents:publish`, and roles are a per-organization matrix,
    // so `agents:edit` plus `collections:edit` and nothing else walks a flow that
    // ends on the knowledge fork. Skipping there stepped one past the end, the
    // clamp put the reader back on the question they had just answered, and Skip
    // offered it again — forever, the close button the only way out.
    rig.can = (permission) => permission === Perm.agentsEdit || permission === Perm.collectionsEdit;
    rig.kbs = [];
    nav.pathname = "/rag";
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));

    const last = result.current.steps.length - 1;
    expect(result.current.steps[last]?.id).toBe("flow-agent-knowledge-ask");
    act(() => useOnboardingStore.getState().setIndex(last));
    expect(result.current.step?.id).toBe("flow-agent-knowledge-ask");

    act(() => result.current.answer("flow-agent-knowledge-ask", "skip"));
    expect(result.current.isActive).toBe(false);
    expect(useOnboardingStore.getState().isOpen).toBe(false);
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

    // Skip past the in-dialog walk to the taught return leg.
    const navAt = result.current.steps.findIndex((s) => s.id === "flow-agent-knowledge-return-nav");
    act(() => useOnboardingStore.getState().setIndex(navAt));
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
    rig.agentDetail = { status: "draft", draft_spec: { model_profile_id: null } };
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    act(() => useOnboardingStore.getState().setFlowAgentId("a-1"));
    act(() => useOnboardingStore.getState().setIndex(2)); // the model step
    expect(result.current.step?.id).toBe("flow-agent-model-add");

    rig.profiles = [{ secret_id: "sec-1" }]; // AddModel creates a new profile mid-flow
    rerender();
    // Frozen: still the add step rather than turning into "pick a model" with
    // nothing to advance it.
    expect(result.current.step?.id).toBe("flow-agent-model-add");
  });

  it("holds the add-model step until the draft itself carries the model", () => {
    // The profile list growing is not enough. Creating a profile selects it on the
    // builder's *local* spec, stored behind a 1.2s debounce — and the step after
    // this one navigates to Knowledge, unmounting the builder and cancelling that
    // save. Advancing on the list left the walk at a Publish that refuses a spec
    // with no model, with no way on.
    rig.profiles = [];
    rig.agentDetail = { status: "draft", draft_spec: { model_profile_id: null } };
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-agent"));
    act(() => useOnboardingStore.getState().setFlowAgentId("a-1"));
    act(() => useOnboardingStore.getState().setIndex(2));
    expect(result.current.step?.id).toBe("flow-agent-model-add");

    rig.profiles = [{ secret_id: "sec-1" }];
    rerender();
    expect(result.current.signalMet).toBe(false);

    rig.agentDetail = { status: "draft", draft_spec: { model_profile_id: "mp-1" } };
    rerender();
    expect(result.current.signalMet).toBe(true);
  });

  it("does not read a background refresh of a cached list as a creation", () => {
    // React Query reports `isLoading` false the moment it has cached data, while a
    // refresh of that cache is still in flight. Baselined on the cached number, the
    // refresh alone — a colleague's row, or one made in another tab — advanced the
    // step with nothing done here.
    rig.skillTotal = 3;
    rig.skillFetching = true;
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-skill"));
    const createAt = result.current.steps.findIndex((s) => s.id === "flow-skill-field-create");
    act(() => useOnboardingStore.getState().setIndex(createAt));
    expect(result.current.step?.id).toBe("flow-skill-field-create");
    // No baseline yet: the count is withheld while the refresh runs.
    expect(result.current.signalMet).toBe(false);

    rig.skillTotal = 4; // the refresh lands, carrying somebody else's skill
    rig.skillFetching = false;
    rerender();
    expect(result.current.signalMet).toBe(false);

    rig.skillTotal = 5; // now the reader creates one
    rerender();
    expect(result.current.signalMet).toBe(true);
  });
});
