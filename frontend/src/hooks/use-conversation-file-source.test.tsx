import { renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useWorkOnStore } from "@/stores/work-on-store";
import { useConversationFileSource } from "./use-conversation-file-source";

const env = vi.hoisted(() => ({ desktop: false }));
vi.mock("./use-shell", () => ({ useShell: () => (env.desktop ? { platform: "macos" } : null) }));
beforeEach(() => {
  env.desktop = false;
  useWorkOnStore.setState({ byConversation: {}, draft: null });
});
it("uses the conversation in a browser or without a local folder", () => {
  expect(renderHook(() => useConversationFileSource("c1")).result.current).toEqual({
    kind: "conversation",
    id: "c1",
  });
  env.desktop = true;
  expect(renderHook(() => useConversationFileSource(null)).result.current).toBeNull();
});
it("uses the approved local folder, including a draft, and keeps computer-wide work separate", () => {
  env.desktop = true;
  useWorkOnStore.getState().set("c1", { folder: "/approved", mode: "read_only" });
  expect(renderHook(() => useConversationFileSource("c1")).result.current).toEqual({
    kind: "local",
    root: "/approved",
  });
  useWorkOnStore.getState().set(null, { folder: "/draft", mode: "full_access" });
  expect(renderHook(() => useConversationFileSource(null)).result.current).toEqual({
    kind: "local",
    root: "/draft",
  });
  useWorkOnStore
    .getState()
    .set("c1", { folder: "/home", mode: "full_access", computer_grant: "all" });
  expect(renderHook(() => useConversationFileSource("c1")).result.current).toEqual({
    kind: "conversation",
    id: "c1",
  });
});
