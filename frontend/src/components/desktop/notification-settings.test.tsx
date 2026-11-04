import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import {
  DesktopNotificationSettings,
  ConversationNotificationToggle,
} from "./notification-settings";
import { useAuthStore } from "@/stores";
import {
  DEFAULT_DESKTOP_NOTIFICATIONS,
  desktopScope,
  useDesktopPreferencesStore,
} from "@/stores/desktop-preferences-store";
const env = vi.hoisted(() => ({
  permission: "denied",
  request: vi.fn(),
  notify: vi.fn(),
  report: vi.fn(),
}));
vi.mock("@/hooks/use-organizations", () => ({ useTenantId: () => "org" }));
vi.mock("@/hooks/use-desktop-readiness", () => ({
  useDesktopReadiness: () => ({
    status: { data: { notifications: env.permission } },
    request: { mutate: env.request, isPending: false },
  }),
}));
vi.mock("@/lib/desktop/commands", () => ({ notify: env.notify }));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  reportShellFailure: env.report,
}));
const scope = desktopScope("me", "org")!;
beforeEach(() => {
  vi.clearAllMocks();
  env.permission = "denied";
  env.notify.mockResolvedValue(undefined);
  useAuthStore.setState({
    user: { id: "me", email: "me@example.test", is_active: true, created_at: "now" },
  });
  useDesktopPreferencesStore.setState({ notifications: {}, reviewed: {} });
});
it("scopes preferences, repairs OS permission and reports test delivery failure", async () => {
  const user = userEvent.setup();
  render(<DesktopNotificationSettings />);
  await user.click(screen.getByRole("switch", { name: "Tasks completed" }));
  expect(useDesktopPreferencesStore.getState().notifications[scope]?.completed).toBe(false);
  await user.click(screen.getByRole("button", { name: "Set up system notifications" }));
  expect(env.request).toHaveBeenCalledWith("notifications");
  await user.click(screen.getByRole("button", { name: "Send a test notification" }));
  expect(env.notify).toHaveBeenCalled();
  env.notify.mockRejectedValueOnce(new Error("denied"));
  await user.click(screen.getByRole("button", { name: "Send a test notification" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not send");
  act(() =>
    useDesktopPreferencesStore
      .getState()
      .setNotifications(scope, { ...DEFAULT_DESKTOP_NOTIFICATIONS, muted_conversations: ["c"] }),
  );
  await user.click(screen.getByRole("button", { name: "Unmute 1 conversation" }));
  expect(useDesktopPreferencesStore.getState().notifications[scope]?.muted_conversations).toEqual(
    [],
  );
});
it("mutes and unmutes one conversation without changing other chats", async () => {
  useDesktopPreferencesStore
    .getState()
    .setNotifications(scope, { ...DEFAULT_DESKTOP_NOTIFICATIONS, muted_conversations: ["other"] });
  const user = userEvent.setup();
  const view = render(<ConversationNotificationToggle conversationId="c" />);
  await user.click(
    screen.getByRole("button", { name: "Mute notifications for this conversation" }),
  );
  expect(useDesktopPreferencesStore.getState().notifications[scope]?.muted_conversations).toEqual([
    "other",
    "c",
  ]);
  await user.click(screen.getByRole("button", { name: "Unmute this conversation" }));
  expect(useDesktopPreferencesStore.getState().notifications[scope]?.muted_conversations).toEqual([
    "other",
  ]);
  view.rerender(<ConversationNotificationToggle conversationId={null} />);
  expect(screen.queryByRole("button")).toBeNull();
});
it("does not offer account controls without an identity", async () => {
  useAuthStore.setState({ user: null });
  env.permission = "granted";
  render(
    <>
      <DesktopNotificationSettings />
      <ConversationNotificationToggle conversationId="c" />
    </>,
  );
  for (const control of screen.getAllByRole("switch")) expect(control).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Set up system notifications" })).toBeNull();
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "Mute notifications for this conversation" }),
    ).toBeNull(),
  );
});
