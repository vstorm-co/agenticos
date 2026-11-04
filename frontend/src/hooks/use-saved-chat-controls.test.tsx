import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useChatControlsStore } from "@/stores/chat-controls-store";
import { useSavedChatControls } from "./use-saved-chat-controls";
const state = vi.hoisted(() => ({ user: "alice", org: "org-a" }));
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (select: (s: { user: { id: string } }) => unknown) =>
    select({ user: { id: state.user } }),
}));
vi.mock("@/stores/org-store", () => ({
  useOrgStore: (select: (s: { activeOrgId: string }) => unknown) =>
    select({ activeOrgId: state.org }),
}));
beforeEach(() => {
  state.user = "alice";
  state.org = "org-a";
  useChatControlsStore.setState({ byScope: {} });
});
it("restores model and approval preferences across mounts", () => {
  const first = renderHook(() => useSavedChatControls(true));
  act(() => first.result.current.update({ modelProfileId: "profile", approvalMode: "ask_all" }));
  first.unmount();
  const second = renderHook(() => useSavedChatControls(true));
  expect(second.result.current.modelProfileId).toBe("profile");
  expect(second.result.current.approvalMode).toBe("ask_all");
});
it("isolates preferences between accounts and organizations", () => {
  const hook = renderHook(() => useSavedChatControls(true));
  act(() =>
    hook.result.current.update({ browser: true, computer: true, modelProfileId: "secret-profile" }),
  );
  state.org = "org-b";
  hook.rerender();
  expect(hook.result.current.modelProfileId).toBeNull();
  expect(hook.result.current.browser).toBe(false);
  state.org = "org-a";
  state.user = "bob";
  hook.rerender();
  expect(hook.result.current.computer).toBe(false);
  state.user = "alice";
  hook.rerender();
  expect(hook.result.current.modelProfileId).toBe("secret-profile");
});
it("never restores approve-all past the current permission or organization ceiling", () => {
  const hook = renderHook(({ mayWaive }: { mayWaive: boolean }) => useSavedChatControls(mayWaive), {
    initialProps: { mayWaive: true },
  });
  act(() => hook.result.current.update({ approvalMode: "approve_all" }));
  expect(hook.result.current.approvalMode).toBe("approve_all");
  hook.rerender({ mayWaive: false });
  expect(hook.result.current.approvalMode).toBe("follow_agent");
});
