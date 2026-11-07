import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { toast } from "sonner";
import { useOrgStore } from "@/stores/org-store";
import { reportShellFailure } from "@/lib/desktop/shell";

import { useConversationStore } from "@/stores";
import { useLocalAccessStore } from "@/stores/local-access-store";
import { useWorkOnStore } from "@/stores/work-on-store";
import type { Agent } from "@/types/agents";

import { useLocalAccessGate, worksOnThisComputer } from "./use-local-access-gate";

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

  it("asks once, then sends and remembers the answer for the agent", async () => {
    const { send, gated } = gate(local);
    gated("hej", ["file"]);
    expect(send).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(useLocalAccessStore.getState().asking).toEqual({
        id: "agent-1",
        name: "AgenticOS",
        coding: false,
      }),
    );
    await act(async () => useLocalAccessStore.getState().answer(whole));
    expect(send).toHaveBeenCalledWith("hej", ["file"]);
    await waitFor(() => expect(useWorkOnStore.getState().targetFor("chat")).toEqual(whole));
    expect(useWorkOnStore.getState().agentTargetFor("agent-1")).toEqual(whole);
  });

  it("sends nothing when the person declines", async () => {
    const { send, gated } = gate(local);
    gated("hej");
    await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
    await act(async () => useLocalAccessStore.getState().answer(null));
    expect(send).not.toHaveBeenCalled();
    expect(useWorkOnStore.getState().agentTargetFor("agent-1")).toBeNull();
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
  await waitFor(() => expect(useLocalAccessStore.getState().asking?.id).toBe(local.id));
  expect(send).not.toHaveBeenCalled();
});
it("asks again for a revoked remembered folder", async () => {
  useWorkOnStore.getState().rememberForAgent(local.id, { folder: "/gone", mode: "full_access" });
  const { send, gated } = gate(local);
  gated("hello");
  await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
  expect(send).not.toHaveBeenCalled();
});
it("does not borrow agent A's whole-computer consent for B", async () => {
  useWorkOnStore.getState().set("chat", whole);
  const { send, gated } = gate({ ...local, id: "agent-B" });
  gated("hello");
  await waitFor(() => expect(useLocalAccessStore.getState().asking?.id).toBe("agent-B"));
  expect(send).not.toHaveBeenCalled();
});
it("does not remember legacy whole-computer consent across chats", async () => {
  const { send, gated } = gate(local);
  gated("hello");
  await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
  const { computer_grant_agent: _owner, ...legacy } = whole;
  await act(async () => useLocalAccessStore.getState().answer(legacy));
  expect(send).toHaveBeenCalledOnce();
  expect(useWorkOnStore.getState().agentTargetFor(local.id)).toBeNull();
});
it("abandons a pending consent if the person changed conversations", async () => {
  const { send, gated } = gate(local);
  gated("hello");
  await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
  useConversationStore.setState({ currentConversationId: "elsewhere" });
  await act(async () => useLocalAccessStore.getState().answer(whole));
  expect(send).not.toHaveBeenCalled();
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
  await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
  await act(async () => useLocalAccessStore.getState().answer(whole));
  expect(send).toHaveBeenCalledWith("hello");
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

it("refuses a legacy remembered consent and asks for this conversation", async () => {
  const { computer_grant_agent: _owner, ...legacy } = whole;
  useWorkOnStore.getState().rememberForAgent(local.id, legacy);
  const { send, gated } = gate(local);
  gated("hello");
  await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
  expect(send).not.toHaveBeenCalled();
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
  await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
  expect(send).not.toHaveBeenCalled();
});

it("asks again after native whole-computer consent was revoked", async () => {
  shell.local.mockResolvedValue({ grants: [], modes: ["full_access"], computer_grants: [] });
  useWorkOnStore.getState().set("chat", whole);
  const { send, gated } = gate(local);
  gated("hello");
  await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
  expect(send).not.toHaveBeenCalled();
});

it("does not reuse a folder after its access mode was narrowed", async () => {
  useWorkOnStore.getState().rememberForAgent(local.id, { folder: "/work", mode: "full_access" });
  const { send, gated } = gate(local);
  gated("hello");
  await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
  expect(send).not.toHaveBeenCalled();
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

it("does not open an access dialog after a synchronous conversation switch", async () => {
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

it("checks the latest agent before applying a delayed native choice", async () => {
  const send = vi.fn();
  const { result, rerender } = renderHook(({ agent }) => useLocalAccessGate(send, agent), {
    initialProps: { agent: local },
  });
  result.current("hello");
  await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
  rerender({ agent: cloud });
  await act(async () => useLocalAccessStore.getState().answer(whole));
  expect(send).not.toHaveBeenCalled();
});

it("remembers a chosen folder for the agent without requiring whole-computer consent", async () => {
  const { send, gated } = gate(local);
  gated("hello");
  await waitFor(() => expect(useLocalAccessStore.getState().asking).not.toBeNull());
  const folder = { folder: "/work", mode: "workspace_write" } as const;
  await act(async () => useLocalAccessStore.getState().answer(folder));
  expect(send).toHaveBeenCalledWith("hello");
  expect(useWorkOnStore.getState().agentTargetFor(local.id)).toEqual(folder);
});

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
