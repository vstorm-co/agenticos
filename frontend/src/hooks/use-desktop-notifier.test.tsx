import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { useDesktopNotifier } from "./use-desktop-notifier";
import {
  desktopScope,
  DEFAULT_DESKTOP_NOTIFICATIONS,
  useDesktopPreferencesStore,
} from "@/stores/desktop-preferences-store";
import type { Notice } from "@/lib/desktop/commands";
const env = vi.hoisted(() => ({
  user: "one" as string | null,
  org: "org",
  focus: vi.fn(),
  notify: vi.fn(),
}));
vi.mock("@/stores", () => ({
  useAuthStore: (select: (value: { user: { id: string } | null }) => unknown) =>
    select({ user: env.user ? { id: env.user } : null }),
}));
vi.mock("./use-organizations", () => ({ useTenantId: () => env.org }));
vi.mock("./use-desktop-active-runs", () => ({ useDesktopActiveRuns: () => ({ runs: [] }) }));
vi.mock("@/lib/desktop/readiness", () => ({ readDesktopFocus: env.focus }));
vi.mock("@/lib/desktop/commands", () => ({ notify: env.notify }));
let client: QueryClient;
function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
const approval: Notice = {
  kind: "approval",
  title: "Private customer name",
  body: "token: confidential",
  path: "/chat?id=chat",
  approval_id: "approval",
  approve_label: "Approve",
  reject_label: "Reject",
};
beforeEach(() => {
  env.user = "one";
  env.org = "org";
  env.focus.mockReset().mockResolvedValue({ focused: false, conversation_id: null });
  env.notify.mockReset().mockResolvedValue(undefined);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  useDesktopPreferencesStore.setState({ notifications: {}, reviewed: {} });
});
it("hides private arguments and removes blind approval actions by default", async () => {
  const view = renderHook(() => useDesktopNotifier(), { wrapper });
  await view.result.current.send(approval, "approval_requested");
  expect(env.notify).toHaveBeenCalledWith(
    expect.objectContaining({ kind: "inbox", path: approval.path }),
  );
  expect(JSON.stringify(env.notify.mock.calls)).not.toContain("confidential");
  expect(env.notify.mock.calls[0]?.[0]).not.toHaveProperty("approval_id");
});
it("retains reviewable approval actions when previews are explicitly enabled", async () => {
  const scope = desktopScope("one", "org")!;
  useDesktopPreferencesStore
    .getState()
    .setNotifications(scope, { ...DEFAULT_DESKTOP_NOTIFICATIONS, hide_previews: false });
  const view = renderHook(() => useDesktopNotifier(), { wrapper });
  await view.result.current.send(approval, "approval_requested");
  expect(env.notify).toHaveBeenCalledWith(approval);
});
it("does not banner the conversation visible in the focused native window", async () => {
  env.focus.mockResolvedValue({ focused: true, conversation_id: "chat" });
  const view = renderHook(() => useDesktopNotifier(), { wrapper });
  await view.result.current.send(approval, "approval_requested");
  expect(env.notify).not.toHaveBeenCalled();
});
it("drops a late focus result when the account changed during the native check", async () => {
  let complete: (value: { focused: boolean; conversation_id: null }) => void = () => {
    throw new Error("not started");
  };
  env.focus.mockImplementation(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  );
  const view = renderHook(() => useDesktopNotifier(), { wrapper });
  const pending = view.result.current.send(approval, "approval_requested");
  await act(async () => {
    env.user = "another";
    view.rerender();
  });
  complete({ focused: false, conversation_id: null });
  await pending;
  expect(env.notify).not.toHaveBeenCalled();
});
