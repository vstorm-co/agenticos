import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useNotificationInbox, useUnreadNotificationCount } from "./use-notifications";
import * as api from "@/lib/notifications-api";
import type { Notification, NotificationPage } from "@/lib/notifications-api";

vi.mock("@/lib/notifications-api", () => ({
  listNotifications: vi.fn(),
  getUnreadNotificationCount: vi.fn(),
  markNotificationRead: vi.fn(),
  markAllNotificationsRead: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function notification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "n1",
    event_type: "run_completed",
    summary: "An agent's run finished.",
    context_url: null,
    read_at: null,
    created_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

function page(items: Notification[], nextCursor: string | null = null): NotificationPage {
  return { items, next_cursor: nextCursor };
}

beforeEach(() => vi.clearAllMocks());

describe("useUnreadNotificationCount", () => {
  it("reports the fetched count", async () => {
    vi.mocked(api.getUnreadNotificationCount).mockResolvedValue(3);
    const { result } = renderHook(() => useUnreadNotificationCount(), { wrapper });

    await waitFor(() => expect(result.current).toBe(3));
  });

  it("reads zero before the first answer arrives", () => {
    vi.mocked(api.getUnreadNotificationCount).mockResolvedValue(3);
    const { result } = renderHook(() => useUnreadNotificationCount(), { wrapper });

    expect(result.current).toBe(0);
  });

  it("does not fetch while disabled", () => {
    vi.mocked(api.getUnreadNotificationCount).mockResolvedValue(3);
    renderHook(() => useUnreadNotificationCount(false), { wrapper });

    expect(api.getUnreadNotificationCount).not.toHaveBeenCalled();
  });
});

describe("useNotificationInbox", () => {
  it("does not fetch until enabled", () => {
    vi.mocked(api.listNotifications).mockResolvedValue(page([]));
    const { result } = renderHook(() => useNotificationInbox(false), { wrapper });

    expect(api.listNotifications).not.toHaveBeenCalled();
    // Nothing has fetched yet, so there is no next page to speak of either -
    // `hasNextPage` is `undefined` at this point, not `false`.
    expect(result.current.hasMore).toBe(false);
  });

  it("lists the first page once enabled", async () => {
    vi.mocked(api.listNotifications).mockResolvedValue(page([notification()]));
    const { result } = renderHook(() => useNotificationInbox(true), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.notifications).toEqual([notification()]);
    expect(result.current.hasMore).toBe(false);
  });

  it("says what went wrong when the list could not be read", async () => {
    vi.mocked(api.listNotifications).mockRejectedValue(new Error("Not authenticated"));
    const { result } = renderHook(() => useNotificationInbox(true), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("Not authenticated"));
  });

  it("refetches on request", async () => {
    vi.mocked(api.listNotifications).mockResolvedValue(page([notification()]));
    const { result } = renderHook(() => useNotificationInbox(true), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.refetch());

    await waitFor(() => expect(api.listNotifications).toHaveBeenCalledTimes(2));
  });

  it("loads a second page and appends it, deduplicating by id", async () => {
    vi.mocked(api.listNotifications).mockImplementation((cursor) =>
      Promise.resolve(
        cursor === "c1"
          ? page([notification({ id: "n1" }), notification({ id: "n2" })])
          : page([notification({ id: "n1" })], "c1"),
      ),
    );
    const { result } = renderHook(() => useNotificationInbox(true), { wrapper });

    await waitFor(() => expect(result.current.hasMore).toBe(true));
    await act(async () => result.current.loadMore());

    await waitFor(() => expect(result.current.hasMore).toBe(false));
    expect(result.current.notifications.map((n) => n.id)).toEqual(["n1", "n2"]);
  });

  it("marks one notification read in place and decrements the count", async () => {
    vi.mocked(api.listNotifications).mockResolvedValue(
      page([notification({ id: "n1" }), notification({ id: "n2" })]),
    );
    vi.mocked(api.markNotificationRead).mockResolvedValue(
      notification({ id: "n1", read_at: "2026-09-02T00:00:00Z" }),
    );
    vi.mocked(api.getUnreadNotificationCount).mockResolvedValue(2);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function TestWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const countHook = renderHook(() => useUnreadNotificationCount(), { wrapper: TestWrapper });
    await waitFor(() => expect(countHook.result.current).toBe(2));
    const inboxHook = renderHook(() => useNotificationInbox(true), { wrapper: TestWrapper });
    await waitFor(() => expect(inboxHook.result.current.isLoading).toBe(false));

    await act(async () => inboxHook.result.current.markRead("n1"));

    expect(api.markNotificationRead).toHaveBeenCalledWith("n1");
    await waitFor(() =>
      expect(inboxHook.result.current.notifications.find((n) => n.id === "n1")?.read_at).toBe(
        "2026-09-02T00:00:00Z",
      ),
    );
    expect(inboxHook.result.current.notifications.find((n) => n.id === "n2")?.read_at).toBeNull();
    await waitFor(() => expect(countHook.result.current).toBe(1));
  });

  it("marks every unread row read and zeroes the count", async () => {
    vi.mocked(api.listNotifications).mockResolvedValue(
      page([
        notification({ id: "n1" }),
        notification({ id: "n2", read_at: "2026-09-01T01:00:00Z" }),
      ]),
    );
    vi.mocked(api.markAllNotificationsRead).mockResolvedValue(1);
    vi.mocked(api.getUnreadNotificationCount).mockResolvedValue(1);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function TestWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const countHook = renderHook(() => useUnreadNotificationCount(), { wrapper: TestWrapper });
    await waitFor(() => expect(countHook.result.current).toBe(1));
    const inboxHook = renderHook(() => useNotificationInbox(true), { wrapper: TestWrapper });
    await waitFor(() => expect(inboxHook.result.current.isLoading).toBe(false));

    await act(async () => inboxHook.result.current.markAllRead());

    await waitFor(() =>
      expect(inboxHook.result.current.notifications.every((n) => n.read_at !== null)).toBe(true),
    );
    // The row already read before the call keeps its own timestamp rather
    // than being overwritten with "now".
    expect(inboxHook.result.current.notifications.find((n) => n.id === "n2")?.read_at).toBe(
      "2026-09-01T01:00:00Z",
    );
    await waitFor(() => expect(countHook.result.current).toBe(0));
  });

  it("subtracts what was actually marked, not a bare zero, when the sweep was capped", async () => {
    // The write path caps how many rows one call marks - a backlog past that
    // cap leaves some rows genuinely still unread, and zeroing the badge
    // regardless would claim it cleared a queue it only partly worked
    // through.
    vi.mocked(api.listNotifications).mockResolvedValue(page([notification({ id: "n1" })]));
    vi.mocked(api.markAllNotificationsRead).mockResolvedValue(500);
    vi.mocked(api.getUnreadNotificationCount).mockResolvedValue(600);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function TestWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const countHook = renderHook(() => useUnreadNotificationCount(), { wrapper: TestWrapper });
    await waitFor(() => expect(countHook.result.current).toBe(600));
    const inboxHook = renderHook(() => useNotificationInbox(true), { wrapper: TestWrapper });
    await waitFor(() => expect(inboxHook.result.current.isLoading).toBe(false));

    await act(async () => inboxHook.result.current.markAllRead());

    await waitFor(() => expect(countHook.result.current).toBe(100));
  });

  it("does not double-decrement when the same row is marked read twice before the cache updates", async () => {
    // A rapid double-click calls this twice for the same row before the
    // first call's own network round trip returns - `NotificationRow`'s
    // `unread` gate reads the same cache both clicks see, unmoved. Two
    // deferred promises let the test control exactly that interleaving:
    // both calls start (and both read the still-unpatched cache) before
    // either's `markNotificationRead` resolves.
    vi.mocked(api.listNotifications).mockResolvedValue(page([notification({ id: "n1" })]));
    let resolveFirst: (n: Notification) => void = () => {};
    let resolveSecond: (n: Notification) => void = () => {};
    vi.mocked(api.markNotificationRead)
      .mockImplementationOnce(() => new Promise((resolve) => (resolveFirst = resolve)))
      .mockImplementationOnce(() => new Promise((resolve) => (resolveSecond = resolve)));
    // Three, not one - a clamp at zero would make a correct single decrement
    // and an incorrect double decrement land on the same number starting
    // from one, and hide the very bug this test exists to catch.
    vi.mocked(api.getUnreadNotificationCount).mockResolvedValue(3);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function TestWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const countHook = renderHook(() => useUnreadNotificationCount(), { wrapper: TestWrapper });
    await waitFor(() => expect(countHook.result.current).toBe(3));
    const inboxHook = renderHook(() => useNotificationInbox(true), { wrapper: TestWrapper });
    await waitFor(() => expect(inboxHook.result.current.isLoading).toBe(false));

    const firstCall = inboxHook.result.current.markRead("n1");
    const secondCall = inboxHook.result.current.markRead("n1");
    await act(async () => {
      resolveFirst(notification({ id: "n1", read_at: "2026-09-02T00:00:00Z" }));
      await firstCall;
      resolveSecond(notification({ id: "n1", read_at: "2026-09-02T00:00:00Z" }));
      await secondCall;
    });

    await waitFor(() => expect(countHook.result.current).toBe(2));
  });

  it("cancels the in-flight count and inbox reads before writing, so a stale poll cannot win", async () => {
    // The count polls every minute in the background; a poll already
    // running when a mark-read commits would otherwise resolve after it
    // and replace the decremented count with the pre-write one it read -
    // the same dedup race `use-notification-preferences.ts` cancels for.
    vi.mocked(api.listNotifications).mockResolvedValue(page([notification({ id: "n1" })]));
    vi.mocked(api.markNotificationRead).mockResolvedValue(
      notification({ id: "n1", read_at: "2026-09-02T00:00:00Z" }),
    );
    vi.mocked(api.getUnreadNotificationCount).mockResolvedValue(1);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const cancelSpy = vi.spyOn(client, "cancelQueries");
    function TestWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    renderHook(() => useUnreadNotificationCount(), { wrapper: TestWrapper });
    const inboxHook = renderHook(() => useNotificationInbox(true), { wrapper: TestWrapper });
    await waitFor(() => expect(inboxHook.result.current.isLoading).toBe(false));

    await act(async () => inboxHook.result.current.markRead("n1"));

    expect(cancelSpy).toHaveBeenCalledWith({ queryKey: ["notifications", "inbox"] });
    expect(cancelSpy).toHaveBeenCalledWith({ queryKey: ["notifications", "unread-count"] });
  });

  it("leaves the cache alone when marking read before any page has loaded", async () => {
    vi.mocked(api.markNotificationRead).mockResolvedValue(
      notification({ id: "n1", read_at: "2026-09-02T00:00:00Z" }),
    );
    const { result } = renderHook(() => useNotificationInbox(false), { wrapper });

    await act(async () => result.current.markRead("n1"));

    expect(result.current.notifications).toEqual([]);
  });

  it("marks a row read without crashing when the badge query has never run", async () => {
    // The badge is its own query, mounted independently of the panel - a
    // reader who opens the list before the count has ever resolved still
    // has a row to mark read, with no cached count to decrement from.
    vi.mocked(api.listNotifications).mockResolvedValue(page([notification({ id: "n1" })]));
    vi.mocked(api.markNotificationRead).mockResolvedValue(
      notification({ id: "n1", read_at: "2026-09-02T00:00:00Z" }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function TestWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => useNotificationInbox(true), { wrapper: TestWrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => result.current.markRead("n1"));

    await waitFor(() =>
      expect(result.current.notifications[0]?.read_at).toBe("2026-09-02T00:00:00Z"),
    );
  });

  it("marks every row read without crashing when the badge query has never run", async () => {
    vi.mocked(api.listNotifications).mockResolvedValue(page([notification({ id: "n1" })]));
    vi.mocked(api.markAllNotificationsRead).mockResolvedValue(1);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function TestWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => useNotificationInbox(true), { wrapper: TestWrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => result.current.markAllRead());

    await waitFor(() => expect(result.current.notifications[0]?.read_at).not.toBeNull());
  });

  it("stamps a read timestamp itself when the server answers with none", async () => {
    // The API always sets `read_at` on a successful mark-read; this is the
    // defensive half for a response shaped otherwise, so a row is not left
    // reading as unread after a call that just marked it read.
    vi.mocked(api.listNotifications).mockResolvedValue(page([notification({ id: "n1" })]));
    vi.mocked(api.markNotificationRead).mockResolvedValue(
      notification({ id: "n1", read_at: null }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function TestWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => useNotificationInbox(true), { wrapper: TestWrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => result.current.markRead("n1"));

    await waitFor(() => expect(result.current.notifications[0]?.read_at).not.toBeNull());
  });
});
