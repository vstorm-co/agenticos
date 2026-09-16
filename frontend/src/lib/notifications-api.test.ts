import { beforeEach, describe, expect, it, vi } from "vitest";

import * as notifications from "./notifications-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

const NOTIFICATION = {
  id: "n1",
  event_type: "run_completed",
  summary: "jarvis's run finished.",
  context_url: null,
  read_at: null,
  created_at: "2026-09-01T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("notifications API", () => {
  it("lists the first page with no cursor param at all", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [NOTIFICATION], next_cursor: "c1" });

    await expect(notifications.listNotifications()).resolves.toEqual({
      items: [NOTIFICATION],
      next_cursor: "c1",
    });
    expect(apiClient.get).toHaveBeenCalledWith("/notifications", { params: undefined });
  });

  it("carries a cursor as a query param", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], next_cursor: null });

    await notifications.listNotifications("c1");

    expect(apiClient.get).toHaveBeenCalledWith("/notifications", { params: { cursor: "c1" } });
  });

  it("unwraps the unread count", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ count: 4 });

    await expect(notifications.getUnreadNotificationCount()).resolves.toBe(4);
    expect(apiClient.get).toHaveBeenCalledWith("/notifications/unread-count");
  });

  it("marks one notification read by id, kept alive past a navigating click", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({
      ...NOTIFICATION,
      read_at: "2026-09-02T00:00:00Z",
    });

    const updated = await notifications.markNotificationRead("n1");

    // `keepalive` because the usual caller is a click on a link with a real
    // destination: the browser can start unloading the page before an
    // ordinary fetch flushes.
    expect(apiClient.patch).toHaveBeenCalledWith("/notifications/n1", undefined, {
      keepalive: true,
    });
    expect(updated.read_at).toBe("2026-09-02T00:00:00Z");
  });

  it("unwraps how many were marked read", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ marked: 3 });

    await expect(notifications.markAllNotificationsRead()).resolves.toBe(3);
    expect(apiClient.post).toHaveBeenCalledWith("/notifications/mark-all-read");
  });
});
