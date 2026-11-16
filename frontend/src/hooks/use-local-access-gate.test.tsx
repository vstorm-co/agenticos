import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { toast } from "sonner";
import { useOrgStore } from "@/stores/org-store";
import { reportShellFailure } from "@/lib/desktop/shell";

import { useConversationStore } from "@/stores";
import { useLocalAccessStore } from "@/stores/local-access-store";
import { useWorkOnStore } from "@/stores/work-on-store";
import type { Agent } from "@/types/agents";

import type { ComputerAccessRequest } from "@/types/chat";

import {
  useComputerAccessOnUse,
  useLocalAccessGate,
  worksOnThisComputer,
} from "./use-local-access-gate";

vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  reportShellFailure: vi.fn(),
}));

const shell = vi.hoisted(() => ({ desktop: true, local: vi.fn() }));
vi.mock("@/lib/desktop/commands", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/commands")>()),
  getLocalState: shell.local,
}));
vi.mock("@/hooks/use-shell", () => ({
  useShell: () => (shell.desktop ? { platform: "macos", window: "main" } : null),
}));

const local = { id: "agent-1", name: "AgenticOS", local_workspace: true } as Agent;
const cloud = { id: "agent-2", name: "Writer" } as Agent;
const whole = {
  folder: "/Users/person",
  mode: "full_access",
  computer_grant: "consent",
  computer_grant_agent: "agent-1",
} as const;

function gate(agent: Agent | undefined) {
  const send = vi.fn();
  const { result } = renderHook(() => useLocalAccessGate(send, agent));
  return { send, gated: result.current };
}

beforeEach(() => {
  vi.clearAllMocks();
  useOrgStore.setState({ activeOrgId: null });
  shell.desktop = true;
  shell.local.mockResolvedValue({
    grants: [{ path: "/work", mode: "workspace_write" }],
    modes: ["workspace_write"],
    computer_grants: ["consent"],
  });
  useConversationStore.setState({ currentConversationId: "chat", pendingProjectId: null });
  useWorkOnStore.setState({ byConversation: { chat: null }, agentTargets: {}, draft: null });
  useLocalAccessStore.setState({ asking: null, resolve: null });
});

describe("worksOnThisComputer", () => {
  it("is an agent with a local workspace or a coding agent on this computer", () => {
    expect(worksOnThisComputer(local)).toBe(true);
    expect(
      worksOnThisComputer({
        ...cloud,
        local_coding_agent: { harness: "codex", access: "edit" },
      } as Agent),
    ).toBe(true);
    expect(worksOnThisComputer(cloud)).toBe(false);
    expect(worksOnThisComputer(undefined)).toBe(false);
  });
});

describe("useLocalAccessGate", () => {
  it("sends straight away for an agent with a cloud workspace", () => {
    const { send, gated } = gate(cloud);
    gated("hej");
    expect(send).toHaveBeenCalledWith("hej");
    expect(useLocalAccessStore.getState().asking).toBeNull();
  });

  it("sends straight away outside the desktop app", () => {
    shell.desktop = false;
    const { send, gated } = gate(local);
    gated("hej");
    expect(send).toHaveBeenCalledWith("hej");
  });

  it("uses the chat's own folder when it has one", async () => {
    useWorkOnStore.getState().set("chat", { folder: "/work", mode: "workspace_write" });
    const { send, gated } = gate(local);
    gated("hej");
    await waitFor(() => expect(send).toHaveBeenCalledOnce());
    expect(useLocalAccessStore.getState().asking).toBeNull();
  });

  it("starts a new chat where the agent was allowed before, without asking", async () => {
    useWorkOnStore.getState().rememberForAgent("agent-1", whole);
    const { send, gated } = gate(local);
    gated("hej");
    await waitFor(() => expect(useWorkOnStore.getState().targetFor("chat")).toEqual(whole));
    expect(send).toHaveBeenCalledWith("hej");
    expect(useLocalAccessStore.getState().asking).toBeNull();
  });

  it("sends without asking when nothing was granted, so the agent asks on use", async () => {
    const { send, gated } = gate(local);
    gated("hej", ["file"]);
    await waitFor(() => expect(send).toHaveBeenCalledWith("hej", ["file"]));
    expect(useLocalAccessStore.getState().asking).toBeNull();
    expect(useWorkOnStore.getState().targetFor("chat")).toBeNull();
  });

  it("settles an earlier question as declined when a second one is asked", async () => {
    const first = useLocalAccessStore
      .getState()
      .request({ id: "agent-1", name: "AgenticOS", coding: false });
    void useLocalAccessStore
      .getState()
      .request({ id: "agent-1", name: "AgenticOS", coding: false });
    await expect(first).resolves.toBeNull();
  });
});

it("does not inherit another agent's global default", async () => {
  useWorkOnStore.getState().set("other", { folder: "/work", mode: "workspace_write" });
  useWorkOnStore.setState({ byConversation: {} });
  const { send, gated } = gate(local);
  gated("hello");
  await waitFor(() => expect(send).toHaveBeenCalledWith("hello"));
  expect(useLocalAccessStore.getState().asking).toBeNull();
});
it("sends without a revoked remembered folder", async () => {
  useWorkOnStore.getState().rememberForAgent(local.id, { folder: "/gone", mode: "full_access" });
  const { send, gated } = gate(local);
  gated("hello");
  await waitFor(() => expect(send).toHaveBeenCalledWith("hello"));
  expect(useLocalAccessStore.getState().asking).toBeNull();
});
it("does not borrow agent A's whole-computer consent for B", async () => {
  useWorkOnStore.getState().set("chat", whole);
  const { send, gated } = gate({ ...local, id: "agent-B" });
  gated("hello");
  await waitFor(() => expect(send).toHaveBeenCalledWith("hello"));
  expect(useLocalAccessStore.getState().asking).toBeNull();
});
it("keeps a project's cloud workspace", () => {
  useConversationStore.setState({ currentConversationId: null, pendingProjectId: "project" });
  const { send, gated } = gate(local);
  gated("hello");
  expect(send).toHaveBeenCalledOnce();
});
it("waits for selected-agent metadata before sending", async () => {
  const send = vi.fn();
  const initial: { agent: Agent | undefined; loading: boolean } = {
    agent: undefined,
    loading: true,
  };
  const { result, rerender } = renderHook(
    ({ agent, loading }: { agent: Agent | undefined; loading: boolean }) =>
      useLocalAccessGate(send, agent, { selectedAgentId: local.id, metadataPending: loading }),
    { initialProps: initial },
  );
  act(() => result.current("hello"));
  expect(send).not.toHaveBeenCalled();
  rerender({ agent: local, loading: false });
  await waitFor(() => expect(send).toHaveBeenCalledWith("hello"));
});

it("fails closed when selected-agent metadata could not load", () => {
  const send = vi.fn();
  const { result } = renderHook(() =>
    useLocalAccessGate(send, undefined, {
      selectedAgentId: local.id,
      metadataPending: false,
    }),
  );
  result.current("hello");
  expect(send).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledOnce();
});

it.each(["agent", "conversation", "organization", "missing"] as const)(
  "does not replay a metadata-waiting message after its %s changed",
  (change) => {
    const send = vi.fn();
    const initial: { agent: Agent | undefined; loading: boolean } = {
      agent: undefined,
      loading: true,
    };
    const { result, rerender } = renderHook(
      ({ agent, loading }: typeof initial) =>
        useLocalAccessGate(send, agent, { selectedAgentId: local.id, metadataPending: loading }),
      { initialProps: initial },
    );
    act(() => result.current("hello"));
    if (change === "conversation")
      useConversationStore.setState({ currentConversationId: "other" });
    if (change === "organization") useOrgStore.setState({ activeOrgId: "other" });
    rerender({
      agent: change === "missing" ? undefined : change === "agent" ? cloud : local,
      loading: false,
    });
    expect(send).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledOnce();
  },
);

it("sends without a legacy remembered consent", async () => {
  const { computer_grant_agent: _owner, ...legacy } = whole;
  useWorkOnStore.getState().rememberForAgent(local.id, legacy);
  const { send, gated } = gate(local);
  gated("hello");
  await waitFor(() => expect(send).toHaveBeenCalledWith("hello"));
  expect(useLocalAccessStore.getState().asking).toBeNull();
});

it("uses legacy native consent only within the conversation that chose it", async () => {
  const { computer_grant_agent: _owner, ...legacy } = whole;
  shell.local.mockResolvedValue({ grants: [], modes: ["full_access"] });
  useWorkOnStore.getState().set("chat", legacy);
  const { send, gated } = gate(local);
  gated("hello");
  await waitFor(() => expect(send).toHaveBeenCalledWith("hello"));
});

it("does not reuse remembered consent when an older app cannot verify it", async () => {
  shell.local.mockResolvedValue({ grants: [], modes: ["full_access"] });
  useWorkOnStore.getState().rememberForAgent(local.id, whole);
  const { send, gated } = gate(local);
  gated("hello");
  await waitFor(() => expect(send).toHaveBeenCalledWith("hello"));
  expect(useLocalAccessStore.getState().asking).toBeNull();
});

it("drops a revoked whole-computer choice and sends without it", async () => {
  shell.local.mockResolvedValue({ grants: [], modes: ["full_access"], computer_grants: [] });
  useWorkOnStore.getState().set("chat", whole);
  const { send, gated } = gate(local);
  gated("hello");
  await waitFor(() => expect(send).toHaveBeenCalledWith("hello"));
  expect(useLocalAccessStore.getState().asking).toBeNull();
});

it("does not reuse a folder after its access mode was narrowed", async () => {
  useWorkOnStore.getState().rememberForAgent(local.id, { folder: "/work", mode: "full_access" });
  const { send, gated } = gate(local);
  gated("hello");
  await waitFor(() => expect(send).toHaveBeenCalledWith("hello"));
  expect(useLocalAccessStore.getState().asking).toBeNull();
});

it.each(["explicit", "remembered"] as const)(
  "abandons %s access if the chat changed during native validation",
  async (choice) => {
    let settle!: (value: { grants: []; modes: []; computer_grants: string[] }) => void;
    shell.local.mockReturnValue(
      new Promise((resolve) => {
        settle = resolve;
      }),
    );
    if (choice === "explicit") useWorkOnStore.getState().set("chat", whole);
    else useWorkOnStore.getState().rememberForAgent(local.id, whole);
    const { send, gated } = gate(local);
    gated("hello");
    await waitFor(() => expect(shell.local).toHaveBeenCalled());
    useConversationStore.setState({ currentConversationId: "other" });
    await act(async () => settle({ grants: [], modes: [], computer_grants: ["consent"] }));
    expect(send).not.toHaveBeenCalled();
    expect(useLocalAccessStore.getState().asking).toBeNull();
  },
);

it("sends nothing after a synchronous conversation switch", async () => {
  const { send, gated } = gate(local);
  gated("hello");
  useConversationStore.setState({ currentConversationId: "other" });
  await act(async () => {});
  expect(send).not.toHaveBeenCalled();
  expect(useLocalAccessStore.getState().asking).toBeNull();
});

it.each([true, false])(
  "reports a native access failure and only toasts in the same context (%s)",
  async (stay) => {
    let reject!: (error: Error) => void;
    shell.local.mockReturnValue(
      new Promise((_, fail) => {
        reject = fail;
      }),
    );
    useWorkOnStore.getState().set("chat", whole);
    const { send, gated } = gate(local);
    gated("hello");
    if (!stay) useOrgStore.setState({ activeOrgId: "other" });
    await act(async () => reject(new Error("Native bridge unavailable")));
    expect(reportShellFailure).toHaveBeenCalledOnce();
    expect(toast.error).toHaveBeenCalledTimes(stay ? 1 : 0);
    expect(send).not.toHaveBeenCalled();
  },
);

it("respects an already-open project's cloud workspace", () => {
  const send = vi.fn();
  const { result } = renderHook(() =>
    useLocalAccessGate(send, local, {
      selectedAgentId: local.id,
      metadataPending: false,
      projectId: "project",
    }),
  );
  result.current("hello");
  expect(send).toHaveBeenCalledWith("hello");
});

describe("useComputerAccessOnUse", () => {
  function onUse(agent: Agent | undefined) {
    const respond = vi.fn();
    const props = { pending: null as ComputerAccessRequest | null, agent };
    const view = renderHook(
      (current: typeof props) => useComputerAccessOnUse({ ...current, respond }),
      { initialProps: props },
    );
    return { respond, view, props };
  }

  it("asks, remembers the choice and releases the requesting run", async () => {
    const { respond, view, props } = onUse(local);
    const asked = { reason: "Read README" };
    view.rerender({ ...props, pending: asked });
    await waitFor(() =>
      expect(useLocalAccessStore.getState().asking).toMatchObject({
        id: local.id,
        reason: "Read README",
      }),
    );
    await act(async () => useLocalAccessStore.getState().answer(whole));
    await waitFor(() => expect(respond).toHaveBeenCalledWith(true));
    expect(useWorkOnStore.getState().targetFor("chat")).toEqual(whole);
    expect(useWorkOnStore.getState().agentTargetFor(local.id)).toEqual(whole);
  });

  it("asks for a local coding delegate under its cloud root agent", async () => {
    const { respond, view, props } = onUse(cloud);
    view.rerender({ ...props, pending: { reason: "Delegate needs files", coding: true } });
    await waitFor(() =>
      expect(useLocalAccessStore.getState().asking).toMatchObject({
        id: cloud.id,
        coding: true,
        reason: "Delegate needs files",
      }),
    );
    await act(async () =>
      useLocalAccessStore.getState().answer({ ...whole, computer_grant_agent: cloud.id }),
    );
    await waitFor(() => expect(respond).toHaveBeenCalledWith(true));
    expect(useWorkOnStore.getState().agentTargetFor(cloud.id)).toMatchObject({
      computer_grant_agent: cloud.id,
    });
  });

  it("discards a native answer after the organization changes in a draft chat", async () => {
    useConversationStore.setState({ currentConversationId: null });
    const { respond, view, props } = onUse(local);
    view.rerender({ ...props, pending: { reason: "Read project" } });
    await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
    useOrgStore.setState({ activeOrgId: "other" });
    await act(async () => useLocalAccessStore.getState().answer(whole));
    await waitFor(() => expect(respond).toHaveBeenCalledWith(false));
    expect(useWorkOnStore.getState().agentTargetFor(local.id)).toBeNull();
  });

  it("does not remember a legacy whole-computer choice for the agent", async () => {
    const { respond, view, props } = onUse(local);
    view.rerender({ ...props, pending: { reason: "x" } });
    await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
    const { computer_grant_agent: _owner, ...legacy } = whole;
    await act(async () => useLocalAccessStore.getState().answer(legacy));
    await waitFor(() => expect(respond).toHaveBeenCalledWith(true));
    expect(useWorkOnStore.getState().agentTargetFor(local.id)).toBeNull();
  });

  it("tells the run when the person declines, and continues nothing", async () => {
    const { respond, view, props } = onUse(local);
    view.rerender({ ...props, pending: { reason: "x" } });
    await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
    await act(async () => useLocalAccessStore.getState().answer(null));
    await waitFor(() => expect(respond).toHaveBeenCalledWith(false));
  });

  it("does not continue in a chat the person left while choosing", async () => {
    const { respond, view, props } = onUse(local);
    const asked = { reason: "x" };
    view.rerender({ ...props, pending: asked });
    await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
    useConversationStore.setState({ currentConversationId: "elsewhere" });
    await act(async () => useLocalAccessStore.getState().answer(whole));
    await waitFor(() => expect(respond).toHaveBeenCalledWith(false));
  });

  it.each([
    ["outside the desktop app", local, false],
    ["for an unknown agent", undefined, true],
  ])("declines at once %s", (_case, agent, desktop) => {
    shell.desktop = desktop;
    const { respond, view, props } = onUse(agent);
    view.rerender({ ...props, pending: { reason: "x" } });
    expect(respond).toHaveBeenCalledWith(false);
    expect(useLocalAccessStore.getState().asking).toBeNull();
  });

  it("reports a failed native question and declines", async () => {
    const failure = new Error("bridge");
    const request = vi
      .spyOn(useLocalAccessStore.getState(), "request")
      .mockRejectedValueOnce(failure);
    const { respond, view, props } = onUse(local);
    view.rerender({ ...props, pending: { reason: "x" } });
    await waitFor(() => expect(respond).toHaveBeenCalledWith(false));
    expect(reportShellFailure).toHaveBeenCalledWith("asking for local access", failure);
    expect(toast.error).toHaveBeenCalled();
    request.mockRestore();
  });
});
