import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import {
  MobileConversationNotifications,
  MobileNotificationPreferences,
  MobilePushFocus,
} from "./notification-preferences";
import type { MobilePushPreferences } from "@/lib/mobile/notifications";
const env = vi.hoisted(() => ({
  read: vi.fn(),
  save: vi.fn(),
  focus: vi.fn(),
  report: vi.fn(),
  user: "me" as string | null,
  path: "/chat",
  shell: { platform: "ios" } as { platform: string } | null,
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-organizations", () => ({ useTenantId: () => "org" }));
vi.mock("@/stores", () => ({
  useAuthStore: (select: (s: { user: { id: string } | null }) => unknown) =>
    select({ user: env.user ? { id: env.user } : null }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => env.path,
  useSearchParams: () => new URLSearchParams("id=c"),
}));
vi.mock("@/lib/mobile/notifications", () => ({
  readMobilePushPreferences: env.read,
  saveMobilePushPreferences: env.save,
  setPushFocus: env.focus,
}));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  reportShellFailure: env.report,
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
const show = (node: React.ReactNode) => (
  <QueryClientProvider
    client={
      new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      })
    }
  >
    {node}
  </QueryClientProvider>
);
beforeEach(() => {
  vi.clearAllMocks();
  env.user = "me";
  env.path = "/chat";
  env.shell = { platform: "ios" };
  env.read.mockResolvedValue({ hide_previews: false, muted_conversations: ["c", "other"] });
  env.save.mockImplementation(async (value: MobilePushPreferences) => value);
  env.focus.mockResolvedValue(undefined);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
it("saves push privacy and per-conversation mute state in the server-backed cache", async () => {
  const user = userEvent.setup();
  render(
    show(
      <>
        <MobileNotificationPreferences />
        <MobileConversationNotifications conversationId="c" />
      </>,
    ),
  );
  await user.click(await screen.findByRole("switch", { name: "Hide notification text" }));
  await waitFor(() =>
    expect(env.save.mock.calls[0]?.[0]).toEqual({
      hide_previews: true,
      muted_conversations: ["c", "other"],
    }),
  );
  await user.click(
    screen.getByRole("button", { name: "Unmute notifications for this conversation" }),
  );
  await waitFor(() =>
    expect(env.save.mock.calls[1]?.[0]).toEqual({
      hide_previews: true,
      muted_conversations: ["other"],
    }),
  );
  await user.click(
    await screen.findByRole("button", { name: "Mute notifications for this conversation" }),
  );
  await waitFor(() =>
    expect(env.save.mock.calls[2]?.[0].muted_conversations).toEqual(["other", "c"]),
  );
  expect(screen.getByText("2 conversations muted on this phone.")).toBeVisible();
});
it("shows loading and retry without inventing preferences, and reports a failed write", async () => {
  const user = userEvent.setup();
  env.read.mockRejectedValueOnce(new Error("offline"));
  render(
    show(
      <>
        <MobileNotificationPreferences />
        <MobileConversationNotifications conversationId={null} />
      </>,
    ),
  );
  await user.click(await screen.findByRole("button", { name: "Check again" }));
  expect(await screen.findByRole("switch")).toBeVisible();
  env.save.mockRejectedValueOnce(new Error("denied"));
  await user.click(screen.getByRole("switch"));
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
});
it("keeps unfetched preferences disabled", () => {
  env.read.mockReturnValue(new Promise(() => {}));
  render(show(<MobileNotificationPreferences />));
  expect(screen.getByRole("button", { name: "Checking…" })).toBeDisabled();
});
it("renews a focused-chat lease and reports lease failures without retaining listeners", async () => {
  vi.useFakeTimers();
  vi.spyOn(document, "hasFocus").mockReturnValue(true);
  const view = render(<MobilePushFocus />);
  await act(async () => {});
  expect(env.focus).toHaveBeenLastCalledWith("c");
  env.focus.mockRejectedValueOnce(new Error("offline"));
  await act(async () => {
    window.dispatchEvent(new Event("focus"));
  });
  expect(env.report).toHaveBeenCalled();
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
    vi.advanceTimersByTime(30_000);
  });
  expect(env.focus).toHaveBeenLastCalledWith(null);
  view.unmount();
  const count = env.focus.mock.calls.length;
  await act(async () => {
    window.dispatchEvent(new Event("focus"));
    vi.advanceTimersByTime(30_000);
  });
  expect(env.focus).toHaveBeenCalledTimes(count);
  env.path = "/runs";
  env.shell = null;
  render(<MobilePushFocus />).unmount();
  env.shell = { platform: "ios" };
  env.user = null;
  render(<MobilePushFocus />).unmount();
  env.user = "me";
  const pending = render(<MobilePushFocus />);
  pending.unmount();
  await act(async () => {});
  expect(env.focus).toHaveBeenCalledTimes(count);
});
