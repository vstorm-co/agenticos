import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useNotificationPreferences } from "./use-notification-preferences";
import * as api from "@/lib/notification-preferences-api";
import type { NotificationPreference } from "@/lib/notification-preferences-api";
import { qk } from "@/lib/query-keys";

vi.mock("@/lib/notification-preferences-api", () => ({
  listNotificationPreferences: vi.fn(),
  updateNotificationPreference: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function preference(overrides: Partial<NotificationPreference> = {}): NotificationPreference {
  return {
    event_type: "run_completed",
    channel: "in_app",
    enabled: true,
    ...overrides,
  };
}

async function hook(preferences: NotificationPreference[] = []) {
  vi.mocked(api.listNotificationPreferences).mockResolvedValue(preferences);
  const rendered = renderHook(() => useNotificationPreferences(), { wrapper });
  await waitFor(() => expect(rendered.result.current.isLoading).toBe(false));
  return rendered.result;
}

beforeEach(() => vi.clearAllMocks());

/**
 * The per-user `(event_type, channel)` preference surface (#1598, Decision
 * 4). Every pair `GET /notifications/preferences` never mentions - because
 * nobody has touched it - defaults to enabled; a mutation replaces its own
 * row in the cache rather than refetching the whole list for one switch.
 */
describe("useNotificationPreferences", () => {
  it("reports an untouched pair as enabled by default", async () => {
    const result = await hook([]);

    expect(result.current.isEnabled("run_completed", "in_app")).toBe(true);
  });

  it("reports a stored pair's own value", async () => {
    const result = await hook([preference({ enabled: false })]);

    expect(result.current.isEnabled("run_completed", "in_app")).toBe(false);
  });

  it("does not confuse two channels of the same event", async () => {
    const result = await hook([preference({ channel: "email", enabled: false })]);

    expect(result.current.isEnabled("run_completed", "email")).toBe(false);
    expect(result.current.isEnabled("run_completed", "in_app")).toBe(true);
  });

  it("does not confuse the same channel of two events", async () => {
    const result = await hook([preference({ event_type: "run_failed", enabled: false })]);

    expect(result.current.isEnabled("run_failed", "in_app")).toBe(false);
    expect(result.current.isEnabled("run_completed", "in_app")).toBe(true);
  });

  it("says what went wrong when the list could not be read", async () => {
    vi.mocked(api.listNotificationPreferences).mockRejectedValue(new Error("Not authenticated"));
    const { result } = renderHook(() => useNotificationPreferences(), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("Not authenticated"));
  });

  it("says nothing went wrong when nothing did", async () => {
    const result = await hook([]);

    expect(result.current.error).toBeNull();
  });

  it("adds the first stored row for a pair rather than nothing", async () => {
    const result = await hook([]);
    vi.mocked(api.updateNotificationPreference).mockResolvedValue(preference({ enabled: false }));

    await act(async () => {
      await result.current.setPreference("run_completed", "in_app", false);
    });

    expect(api.updateNotificationPreference).toHaveBeenCalledWith({
      event_type: "run_completed",
      channel: "in_app",
      enabled: false,
    });
    await waitFor(() => expect(result.current.isEnabled("run_completed", "in_app")).toBe(false));
    expect(result.current.preferences).toHaveLength(1);
  });

  it("replaces an existing row instead of adding a second one for it", async () => {
    const result = await hook([preference({ enabled: false })]);
    vi.mocked(api.updateNotificationPreference).mockResolvedValue(preference({ enabled: true }));

    await act(async () => {
      await result.current.setPreference("run_completed", "in_app", true);
    });

    await waitFor(() => expect(result.current.isEnabled("run_completed", "in_app")).toBe(true));
    expect(result.current.preferences).toHaveLength(1);
  });

  it("cancels the in-flight list read before writing, so a stale refetch cannot win (#1598)", async () => {
    // A background refetch already running when this write starts would
    // otherwise resolve after `setQueryData` and replace the just-written
    // row with the pre-write value it read - the same dedup race
    // `use-secrets.ts`'s `invalidate` and `use-sharing.ts` cancel for.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const cancelSpy = vi.spyOn(client, "cancelQueries");
    function ownWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    vi.mocked(api.listNotificationPreferences).mockResolvedValue([]);
    const { result } = renderHook(() => useNotificationPreferences(), { wrapper: ownWrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    vi.mocked(api.updateNotificationPreference).mockResolvedValue(preference({ enabled: true }));
    await act(async () => {
      await result.current.setPreference("run_completed", "in_app", true);
    });

    expect(cancelSpy).toHaveBeenCalledWith({ queryKey: qk.notifications.preferences() });
  });
});
