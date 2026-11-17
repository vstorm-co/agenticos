import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { chatSendModeScope } from "@/lib/chat-send-mode";
import { useChatSendModePreference, useChatSendModeStore } from "./chat-send-mode-store";

const scope = chatSendModeScope("account-1", "org-1", "agent-1")!;

afterEach(async () => {
  localStorage.clear();
  useChatSendModeStore.setState({ byScope: {} });
  await useChatSendModeStore.persist.rehydrate();
});

describe("chat send mode preferences", () => {
  it("isolates choices by account, organization and agent", () => {
    const otherAgent = chatSendModeScope("account-1", "org-1", "agent-2")!;
    const otherOrganization = chatSendModeScope("account-1", "org-2", "agent-1")!;

    useChatSendModeStore.getState().setMode(scope, "steer");

    expect(useChatSendModeStore.getState().byScope[scope]).toBe("steer");
    expect(useChatSendModeStore.getState().byScope[otherAgent]).toBeUndefined();
    expect(useChatSendModeStore.getState().byScope[otherOrganization]).toBeUndefined();
  });

  it("defaults to Queue and keeps the selected mode for the same agent scope", () => {
    const { result, unmount } = renderHook(() =>
      useChatSendModePreference("account-1", "org-1", "agent-1"),
    );
    expect(result.current.mode).toBe("queue");

    act(() => result.current.setMode("steer"));

    expect(result.current.mode).toBe("steer");
    expect(useChatSendModeStore.getState().byScope[scope]).toBe("steer");
    unmount();
  });

  it("keeps Queue and stores nothing until the account, organization and agent identity is resolved", () => {
    const { result } = renderHook(() => useChatSendModePreference(undefined, "org-1", undefined));

    expect(result.current.mode).toBe("queue");
    act(() => result.current.setMode("steer"));

    expect(result.current.mode).toBe("queue");
    expect(useChatSendModeStore.getState().byScope).toEqual({});
    act(() => useChatSendModeStore.getState().setMode("bad-scope", "steer"));
    expect(useChatSendModeStore.getState().byScope).toEqual({});
  });

  it("keeps a separate preference for the general assistant without an agent sentinel", async () => {
    const generalScope = chatSendModeScope("account-1", "org-1", null)!;
    const { result, unmount } = renderHook(() =>
      useChatSendModePreference("account-1", "org-1", null),
    );
    expect(result.current.mode).toBe("queue");

    act(() => result.current.setMode("steer"));

    expect(result.current.mode).toBe("steer");
    expect(useChatSendModeStore.getState().byScope[generalScope]).toBe("steer");
    expect(useChatSendModeStore.getState().byScope[scope]).toBeUndefined();
    unmount();

    await useChatSendModeStore.persist.rehydrate();
    expect(useChatSendModeStore.getState().byScope[generalScope]).toBe("steer");
  });

  it("persists only mode preferences and drops invalid saved values during hydration", async () => {
    useChatSendModeStore.getState().setMode(scope, "steer");
    const stored = JSON.parse(localStorage.getItem("chat-send-mode") ?? "null");
    expect(stored.state).toEqual({ byScope: { [scope]: "steer" } });
    expect(JSON.stringify(stored)).not.toContain("message body");

    localStorage.setItem(
      "chat-send-mode",
      JSON.stringify({
        state: {
          byScope: {
            [scope]: "steer",
            badScope: "steer",
            [JSON.stringify(["account-1", "org-1", "agent-2"])]: "send-now",
          },
        },
      }),
    );
    await useChatSendModeStore.persist.rehydrate();

    expect(useChatSendModeStore.getState().byScope).toEqual({ [scope]: "steer" });

    for (const byScope of [null, "invalid", []]) {
      localStorage.setItem("chat-send-mode", JSON.stringify({ state: { byScope } }));
      await useChatSendModeStore.persist.rehydrate();
      expect(useChatSendModeStore.getState().byScope).toEqual({});
    }
  });
});
