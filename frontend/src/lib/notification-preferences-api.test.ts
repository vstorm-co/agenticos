import { beforeEach, describe, expect, it, vi } from "vitest";

import * as preferences from "./notification-preferences-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), patch: vi.fn(), put: vi.fn() },
}));

/**
 * The per-user notification channel preferences (#1598, Decision 4).
 *
 * Only the "togglable" `(event_type, channel)` pairs ever travel through
 * these two calls - the backend refuses anything else with a 400, which is
 * `use-notification-preferences`'s job to surface, not this thin client's.
 */
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({
    items: [{ event_type: "run_completed", channel: "in_app", enabled: true }],
  });
  vi.mocked(apiClient.patch).mockResolvedValue({
    event_type: "run_completed",
    channel: "in_app",
    enabled: false,
  });
});

describe("notification preferences API", () => {
  it("unwraps the list", async () => {
    await expect(preferences.listNotificationPreferences()).resolves.toEqual([
      { event_type: "run_completed", channel: "in_app", enabled: true },
    ]);
    expect(apiClient.get).toHaveBeenCalledWith("/notifications/preferences");
  });

  it("patches one pair and returns its new value", async () => {
    const updated = await preferences.updateNotificationPreference({
      event_type: "run_completed",
      channel: "in_app",
      enabled: false,
    });

    expect(apiClient.patch).toHaveBeenCalledWith("/notifications/preferences", {
      event_type: "run_completed",
      channel: "in_app",
      enabled: false,
    });
    expect(updated).toEqual({ event_type: "run_completed", channel: "in_app", enabled: false });
  });
});

it("reads private destinations without treating them as event preferences", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], destinations: [] });
  await expect(preferences.listNotificationRoutes()).resolves.toEqual({
    items: [],
    destinations: [],
  });
  expect(apiClient.get).toHaveBeenCalledWith("/notifications/destinations");
});
it("revokes a route with an explicit null rather than omitting the change", async () => {
  vi.mocked(apiClient.put).mockResolvedValue({ items: [], destinations: [] });
  await preferences.replaceNotificationRoute({ channel: "teams", session_id: null });
  expect(apiClient.put).toHaveBeenCalledWith("/notifications/destinations", {
    channel: "teams",
    session_id: null,
  });
});
