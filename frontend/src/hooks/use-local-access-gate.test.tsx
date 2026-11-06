import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useConversationStore } from "@/stores";
import { useLocalAccessStore } from "@/stores/local-access-store";
import { useWorkOnStore } from "@/stores/work-on-store";
import type { Agent } from "@/types/agents";

import { useLocalAccessGate, worksOnThisComputer } from "./use-local-access-gate";

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
