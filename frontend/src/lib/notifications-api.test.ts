import { beforeEach, describe, expect, it, vi } from "vitest";

import * as notifications from "./notifications-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
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

  it("unwraps the unread count and whether the scan reached the end of it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ count: 4, approximate: true });

    await expect(notifications.getUnreadNotificationCount()).resolves.toEqual({
      count: 4,
      approximate: true,
    });
    expect(apiClient.get).toHaveBeenCalledWith("/notifications/unread-count");
  });

  it("reads a count with no approximate flag as an exact one", async () => {
    // A deployment answering the older shape, and the shape the field defaults
    // to on the wire.
    vi.mocked(apiClient.get).mockResolvedValue({ count: 4 });

    await expect(notifications.getUnreadNotificationCount()).resolves.toEqual({
      count: 4,
      approximate: false,
    });
  });

  it("reads a missing count as none rather than undefined", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({});

    await expect(notifications.getUnreadNotificationCount()).resolves.toEqual({
      count: 0,
      approximate: false,
    });
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

  it("unwraps how many were marked read, and where to carry on from", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      marked: 3,
      remaining: true,
      next_cursor: "c1",
    });

    await expect(notifications.markAllNotificationsRead()).resolves.toEqual({
      marked: 3,
      remaining: true,
      next_cursor: "c1",
    });
    expect(apiClient.post).toHaveBeenCalledWith("/notifications/mark-all-read", undefined, {
      params: undefined,
    });
  });

  it("carries a cursor back so the next sweep starts past this one", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ marked: 1, remaining: false, next_cursor: null });

    await notifications.markAllNotificationsRead("c1");

    expect(apiClient.post).toHaveBeenCalledWith("/notifications/mark-all-read", undefined, {
      params: { cursor: "c1" },
    });
  });

  it("reads a sweep that answered none of the three fields as an empty one", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({});

    await expect(notifications.markAllNotificationsRead()).resolves.toEqual({
      marked: 0,
      remaining: false,
      next_cursor: null,
    });
  });

  it("dismisses one row, and survives the page unloading under it", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);

    await expect(notifications.dismissNotification("n1")).resolves.toBeUndefined();

    // `keepalive` for the same reason the mark-read call takes it: the row
    // being cleared is often the one whose link the click is already
    // following.
    expect(apiClient.delete).toHaveBeenCalledWith("/notifications/n1", { keepalive: true });
  });

  it("unwraps how many the clear actually took", async () => {
    // A number rather than a 204: the sweep is capped, so a caller has to be
    // able to tell an emptied inbox from a truncated one.
    vi.mocked(apiClient.delete).mockResolvedValue({ cleared: 12 });

    await expect(notifications.clearNotifications()).resolves.toBe(12);
    expect(apiClient.delete).toHaveBeenCalledWith("/notifications");
  });
});
