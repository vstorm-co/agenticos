import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { NotificationBell } from "./notification-bell";
import type { Notification } from "@/lib/notifications-api";

const useUnreadNotificationCountMock = vi.fn();
const useNotificationInboxMock = vi.fn();

vi.mock("@/hooks", () => ({
  useUnreadNotificationCount: () => useUnreadNotificationCountMock(),
  useNotificationInbox: (...args: unknown[]) => useNotificationInboxMock(...args),
}));

function notification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "n1",
    event_type: "run_completed",
    summary: "jarvis's run finished.",
    context_url: null,
    read_at: null,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

function renderBell(
  variant: "row" | "icon" = "row",
  inbox: Partial<ReturnType<typeof useNotificationInboxMock>> = {},
) {
  useNotificationInboxMock.mockReturnValue({
    notifications: [],
    isLoading: false,
    error: null,
    hasMore: false,
    isLoadingMore: false,
    loadMore: vi.fn(),
    refetch: vi.fn(),
    markRead: vi.fn().mockResolvedValue(undefined),
    markAllRead: vi.fn().mockResolvedValue(undefined),
    ...inbox,
  });
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <NotificationBell variant={variant} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  useUnreadNotificationCountMock.mockReset();
  useUnreadNotificationCountMock.mockReturnValue(0);
  useNotificationInboxMock.mockReset();
});

describe("NotificationBell", () => {
  it("shows the unread count on the row trigger", () => {
    useUnreadNotificationCountMock.mockReturnValue(3);
    renderBell("row");

    expect(screen.getByRole("button", { name: /Notifications/ })).toHaveTextContent("3");
  });

  it("shows no badge at all when nothing is unread", () => {
    useUnreadNotificationCountMock.mockReturnValue(0);
    renderBell("row");

    expect(screen.getByRole("button", { name: /Notifications/ })).not.toHaveTextContent(/\d/);
  });

  it("caps the visible count rather than growing the badge without bound", () => {
    useUnreadNotificationCountMock.mockReturnValue(140);
    renderBell("row");

    expect(screen.getByRole("button", { name: /Notifications/ })).toHaveTextContent("99+");
  });

  it("opens on the icon trigger too, without the row's own label", () => {
    renderBell("icon");

    expect(screen.getByRole("button", { name: /Notifications/ })).toBeVisible();
  });

  it("lists notifications once opened", async () => {
    renderBell("row", { notifications: [notification()] });

    await userEvent.click(screen.getByRole("button", { name: /Notifications/ }));

    expect(await screen.findByText("jarvis's run finished.")).toBeVisible();
  });

  it("says nothing is waiting, rather than drawing an empty list", async () => {
    renderBell("row", { notifications: [] });

    await userEvent.click(screen.getByRole("button", { name: /Notifications/ }));

    expect(await screen.findByText("No notifications yet")).toBeVisible();
  });

  it("says the list could not be read", async () => {
    renderBell("row", { error: "Not authenticated" });

    await userEvent.click(screen.getByRole("button", { name: /Notifications/ }));

    expect(await screen.findByText("Not authenticated")).toBeVisible();
  });

  it("offers mark-all-read only while something is unread", async () => {
    useUnreadNotificationCountMock.mockReturnValue(0);
    renderBell("row", { notifications: [notification({ read_at: "2026-09-01T00:00:00Z" })] });

    await userEvent.click(screen.getByRole("button", { name: /Notifications/ }));

    expect(await screen.findByText("jarvis's run finished.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Mark all read" })).toBeNull();
  });

  it("still offers mark-all-read when the loaded page is read but the badge is not", async () => {
    // The loaded page can be all-read while an unpaged older page still holds
    // an unread row - the offer has to track the same unread-count query the
    // badge reads, not what happens to be on screen.
    useUnreadNotificationCountMock.mockReturnValue(1);
    renderBell("row", { notifications: [notification({ read_at: "2026-09-01T00:00:00Z" })] });

    await userEvent.click(screen.getByRole("button", { name: /Notifications/ }));

    expect(await screen.findByText("jarvis's run finished.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Mark all read" })).toBeVisible();
  });

  it("marks everything read on request", async () => {
    useUnreadNotificationCountMock.mockReturnValue(1);
    const markAllRead = vi.fn().mockResolvedValue(undefined);
    renderBell("row", { notifications: [notification()], markAllRead });

    await userEvent.click(screen.getByRole("button", { name: /Notifications/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Mark all read" }));

    expect(markAllRead).toHaveBeenCalledOnce();
  });

  it("does not raise an unhandled rejection when marking read fails", async () => {
    // A row the read-time gate has since hidden, or a dropped connection -
    // this is fire-and-forget from the row's own click, so a rejection must
    // not escape as an unhandled one.
    const markRead = vi.fn().mockRejectedValue(new Error("gone"));
    renderBell("row", { notifications: [notification()], markRead });

    await userEvent.click(screen.getByRole("button", { name: /Notifications/ }));
    await userEvent.click(await screen.findByText("jarvis's run finished."));

    expect(markRead).toHaveBeenCalledWith("n1");
  });

  it("offers to load more once there is a next page", async () => {
    const loadMore = vi.fn();
    renderBell("row", { notifications: [notification()], hasMore: true, loadMore });

    await userEvent.click(screen.getByRole("button", { name: /Notifications/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Load more" }));

    expect(loadMore).toHaveBeenCalledOnce();
  });
});
