import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useConversationStore } from "@/stores";
import { useLocalAccessStore } from "@/stores/local-access-store";
import { useWorkOnStore } from "@/stores/work-on-store";
import type { Agent } from "@/types/agents";

import { useLocalAccessGate, worksOnThisComputer } from "./use-local-access-gate";

const shell = vi.hoisted(() => ({ desktop: true }));
vi.mock("@/hooks/use-shell", () => ({
  useShell: () => (shell.desktop ? { platform: "macos", window: "main" } : null),
}));

const local = { id: "agent-1", name: "AgenticOS", local_workspace: true } as Agent;
const cloud = { id: "agent-2", name: "Writer" } as Agent;
const whole = { folder: "/Users/person", mode: "full_access", computer_grant: "consent" } as const;

function gate(agent: Agent | undefined) {
  const send = vi.fn();
  const { result } = renderHook(() => useLocalAccessGate(send, agent));
  return { send, gated: result.current };
}

beforeEach(() => {
  shell.desktop = true;
  useConversationStore.setState({ currentConversationId: "chat" });
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

  it("uses the chat's own folder when it has one", () => {
    useWorkOnStore.getState().set("chat", { folder: "/work", mode: "workspace_write" });
    const { send, gated } = gate(local);
    gated("hej");
    expect(send).toHaveBeenCalledOnce();
    expect(useLocalAccessStore.getState().asking).toBeNull();
  });

  it("starts a new chat where the agent was allowed before, without asking", () => {
    useWorkOnStore.getState().rememberForAgent("agent-1", whole);
    const { send, gated } = gate(local);
    gated("hej");
    expect(useWorkOnStore.getState().targetFor("chat")).toEqual(whole);
    expect(send).toHaveBeenCalledWith("hej");
    expect(useLocalAccessStore.getState().asking).toBeNull();
  });

  it("asks once, then sends and remembers the answer for the agent", async () => {
    const { send, gated } = gate(local);
    gated("hej", ["file"]);
    expect(send).not.toHaveBeenCalled();
    expect(useLocalAccessStore.getState().asking).toEqual({
      id: "agent-1",
      name: "AgenticOS",
      coding: false,
    });
    await act(async () => useLocalAccessStore.getState().answer(whole));
    expect(send).toHaveBeenCalledWith("hej", ["file"]);
    expect(useWorkOnStore.getState().targetFor("chat")).toEqual(whole);
    expect(useWorkOnStore.getState().agentTargetFor("agent-1")).toEqual(whole);
  });

  it("sends nothing when the person declines", async () => {
    const { send, gated } = gate(local);
    gated("hej");
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
