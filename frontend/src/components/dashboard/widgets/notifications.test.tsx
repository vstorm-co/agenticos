import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { TooltipProvider } from "@/components/ui";
import { NotificationsWidget } from "./notifications";
import type { Notification } from "@/lib/notifications-api";
import type { Period } from "@/lib/dashboard/period";

const useNotificationInboxMock = vi.fn();

vi.mock("@/hooks", () => ({
  useNotificationInbox: (...args: unknown[]) => useNotificationInboxMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-07-19", to: "2026-08-18" };

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

function renderWidget(overrides: Partial<ReturnType<typeof useNotificationInboxMock>> = {}) {
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
    ...overrides,
  });
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <TooltipProvider>
        <NotificationsWidget title="Notifications" hint="" period={PERIOD} />
      </TooltipProvider>
    </NextIntlClientProvider>,
  );
}

beforeEach(() => useNotificationInboxMock.mockReset());

describe("the notifications widget", () => {
  it("shows the most recent notifications", () => {
    renderWidget({ notifications: [notification({ summary: "jarvis's run finished." })] });

    expect(screen.getByText("jarvis's run finished.")).toBeVisible();
  });

  it("stops at five rows and leaves the rest to the bell", () => {
    renderWidget({
      notifications: Array.from({ length: 8 }, (_, index) =>
        notification({ id: `n-${index}`, summary: `Notification ${index}` }),
      ),
    });

    expect(screen.getAllByRole("listitem")).toHaveLength(5);
  });

  it("says nothing is waiting, rather than drawing an empty list", () => {
    renderWidget({ notifications: [] });

    expect(screen.getByText("Nothing here yet")).toBeVisible();
  });

  it("draws a placeholder while the list is being read", () => {
    renderWidget({ isLoading: true });

    expect(screen.queryByText("Nothing here yet")).toBeNull();
  });

  it("says the list could not be read, and retries through the same hook", async () => {
    const refetch = vi.fn();
    renderWidget({ error: "Not authenticated", refetch });

    expect(screen.queryByText("Nothing here yet")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("marks an unread row read on click, through a link when it has a destination", async () => {
    const markRead = vi.fn().mockResolvedValue(undefined);
    renderWidget({
      notifications: [notification({ context_url: "https://app.example.com/agents/a1" })],
      markRead,
    });

    await userEvent.click(screen.getByText("jarvis's run finished."));

    expect(markRead).toHaveBeenCalledWith("n1");
  });

  it("marks an unread row read on click when it has no destination", async () => {
    const markRead = vi.fn().mockResolvedValue(undefined);
    renderWidget({ notifications: [notification({ context_url: null })], markRead });

    await userEvent.click(screen.getByText("jarvis's run finished."));

    expect(markRead).toHaveBeenCalledWith("n1");
  });

  it("does not raise an unhandled rejection when marking read fails", async () => {
    // A row the read-time gate has since hidden, or a dropped connection -
    // this is fire-and-forget from the row's own click, so a rejection
    // must not escape as an unhandled one.
    const markRead = vi.fn().mockRejectedValue(new Error("gone"));
    renderWidget({ notifications: [notification({ context_url: null })], markRead });

    await userEvent.click(screen.getByText("jarvis's run finished."));

    expect(markRead).toHaveBeenCalledWith("n1");
  });

  it("says which rows are unread, not only by colour", async () => {
    // A link row's accessible name is its summary either way, so the dot and
    // the font weight are the only thing distinguishing read from unread -
    // neither of which a screen reader announces.
    renderWidget({
      notifications: [
        notification({ id: "n1", summary: "unread one", context_url: "/runs/1" }),
        notification({
          id: "n2",
          summary: "read one",
          context_url: "/runs/2",
          read_at: "2026-09-01T00:00:00Z",
        }),
      ],
    });

    expect(screen.getByText("unread one").closest("a")).toHaveTextContent("Unread");
    expect(screen.getByText("read one").closest("a")).toHaveTextContent("Read");
  });

  it("does not re-mark an already-read row", async () => {
    const markRead = vi.fn().mockResolvedValue(undefined);
    renderWidget({
      notifications: [notification({ read_at: "2026-09-01T00:00:00Z", context_url: null })],
      markRead,
    });

    const row = screen.getByText("jarvis's run finished.");
    expect(row.closest("button")).toBeDisabled();
    await userEvent.click(row);
    expect(markRead).not.toHaveBeenCalled();
  });
});
