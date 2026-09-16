import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NotificationsSettingsPage from "./page";
import { apiClient } from "@/lib/api-client";
import type { User } from "@/types";
import type { NotificationPreference } from "@/lib/notification-preferences-api";

/**
 * The guard for a page that once lied.
 *
 * `/settings/notifications` used to offer four toggles that saved to
 * `localStorage`, which no sender ever read. The toggles are back, but each
 * one now writes a `notify_*` column through PATCH `/users/me` that
 * `NotificationService` consults before sending - so what this file pins is
 * the page's half of that contract: a switch renders the stored value, a flip
 * sends exactly one field to the server, and nothing touches `localStorage`.
 *
 * The second section (#1598, Decision 4) is the same contract one layer up:
 * `useNotificationPreferences` is mocked here rather than exercised for real
 * - its own wiring to `GET`/`PATCH /notifications/preferences` is
 * `use-notification-preferences.test.ts`'s job - so what this file pins for
 * it is that the page renders exactly the fourteen togglable pairs the
 * backend's `_TOGGLABLE_PAIRS` produces, in the shape the hook hands back.
 */

vi.mock("@/lib/api-client", () => ({
  apiClient: { patch: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn() },
}));

const setUser = vi.fn();
const setPreference = vi.fn();
let currentUser: Partial<User>;
let currentPreferences: NotificationPreference[];
let preferencesLoading: boolean;
let preferencesError: string | null;

vi.mock("@/hooks", () => ({
  useAuth: () => ({ user: currentUser }),
  useNotificationPreferences: () => ({
    preferences: currentPreferences,
    isLoading: preferencesLoading,
    error: preferencesError,
    isEnabled: (eventType: string, channel: string) => {
      const stored = currentPreferences.find(
        (p) => p.event_type === eventType && p.channel === channel,
      );
      return stored?.enabled ?? true;
    },
    setPreference,
  }),
}));

vi.mock("@/stores", () => ({
  useAuthStore: () => ({ setUser }),
}));

function makeUser(overrides: Partial<User> = {}): Partial<User> {
  return {
    id: "u-1",
    email: "owner@acme.test",
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    notify_budget_alerts: true,
    notify_approval_requests: true,
    notify_usage_reports: true,
    ...overrides,
  };
}

describe("the notifications settings page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    currentUser = makeUser();
    currentPreferences = [];
    preferencesLoading = false;
    preferencesError = null;
  });

  it("offers one legacy switch per email PATCH /users/me still gates", () => {
    render(<NotificationsSettingsPage />);

    // Mirrors NotificationService: budget_exceeded, approval_requested,
    // usage_report - each event's *email* channel, unchanged by Decision 4.
    // A fourth switch here means a sender was added without wiring its
    // preference, or a toggle was invented without a sender.
    expect(screen.getByRole("switch", { name: "Budget alerts" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Approval requests" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Usage reports" })).toBeInTheDocument();
  });

  it("offers exactly the fourteen togglable pairs the backend produces", () => {
    render(<NotificationsSettingsPage />);

    // Four events offer both channels (2 switches each), five offer only
    // in-app (1 each): 4*2 + 5 = 13... no - run_completed, run_failed,
    // ingestion_completed, ingestion_failed and announcement each offer both
    // (5*2 = 10); budget_exceeded, approval_requested, usage_report and
    // agent_usage_report offer only in-app (4*1 = 4). 10 + 4 = 14, plus the
    // three legacy email switches above = 17 switches on the page total.
    expect(screen.getByRole("switch", { name: "Run completed - In-app" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Run completed - Email" })).toBeInTheDocument();
    expect(
      screen.getByRole("switch", { name: "Per-agent usage report - In-app" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("switch", { name: "Per-agent usage report - Email" }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole("switch")).toHaveLength(17);
  });

  it("renders the stored preference, not a hardcoded on", () => {
    currentUser = makeUser({ notify_usage_reports: false });
    render(<NotificationsSettingsPage />);

    expect(screen.getByRole("switch", { name: "Usage reports" })).not.toBeChecked();
    expect(screen.getByRole("switch", { name: "Budget alerts" })).toBeChecked();
  });

  it("treats a user from before the columns existed as subscribed", () => {
    // A persisted auth store can hold a user shape that predates the
    // preferences; absent must read as the server default, which is true.
    currentUser = makeUser({
      notify_budget_alerts: undefined,
      notify_approval_requests: undefined,
      notify_usage_reports: undefined,
    });
    render(<NotificationsSettingsPage />);

    for (const toggle of screen.getAllByRole("switch")) {
      expect(toggle).toBeChecked();
    }
  });

  it("saves a flip to the server and keeps the response as the new user", async () => {
    const updated = makeUser({ notify_budget_alerts: false });
    vi.mocked(apiClient.patch).mockResolvedValue(updated);
    render(<NotificationsSettingsPage />);

    await userEvent.click(screen.getByRole("switch", { name: "Budget alerts" }));

    // Exactly one field: a PATCH that re-sends the whole user would silently
    // overwrite whatever another tab changed in the meantime.
    expect(apiClient.patch).toHaveBeenCalledWith("/users/me", { notify_budget_alerts: false });
    await waitFor(() => expect(setUser).toHaveBeenCalledWith(updated));
  });

  it("keeps the old state when the save fails", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("network down"));
    render(<NotificationsSettingsPage />);

    await userEvent.click(screen.getByRole("switch", { name: "Usage reports" }));

    await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
    expect(setUser).not.toHaveBeenCalled();
    expect(screen.getByRole("switch", { name: "Usage reports" })).toBeChecked();
  });

  it("writes nothing to local storage", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(makeUser());
    render(<NotificationsSettingsPage />);

    await userEvent.click(screen.getByRole("switch", { name: "Budget alerts" }));
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());

    // The original bug: preferences that lived and died in the browser.
    expect(localStorage.length).toBe(0);
  });

  it("renders a stored preference rather than the unset default", () => {
    currentPreferences = [{ event_type: "run_failed", channel: "email", enabled: false }];
    render(<NotificationsSettingsPage />);

    expect(screen.getByRole("switch", { name: "Run failed - Email" })).not.toBeChecked();
    expect(screen.getByRole("switch", { name: "Run failed - In-app" })).toBeChecked();
  });

  it("flipping a preference switch calls setPreference with the pair and the new value", async () => {
    setPreference.mockResolvedValue(undefined);
    render(<NotificationsSettingsPage />);

    await userEvent.click(screen.getByRole("switch", { name: "Run completed - In-app" }));

    expect(setPreference).toHaveBeenCalledWith("run_completed", "in_app", false);
  });

  it("shows no preference switch, fabricating no value, when the list failed to load", () => {
    preferencesError = "Not authenticated";
    render(<NotificationsSettingsPage />);

    // Every unset pair reads as enabled by default - true only for a
    // successful, empty read. Rendering the switches here would present
    // every one of them as on regardless of what is actually saved.
    expect(screen.queryByRole("switch", { name: "Run completed - In-app" })).toBeNull();
    expect(screen.getByText("Not authenticated")).toBeInTheDocument();
    // The first section answers to `user`, not this hook, and still works.
    expect(screen.getByRole("switch", { name: "Budget alerts" })).toBeInTheDocument();
  });

  it("disables every preference switch while the list is still loading", () => {
    preferencesLoading = true;
    render(<NotificationsSettingsPage />);

    expect(screen.getByRole("switch", { name: "Run completed - In-app" })).toBeDisabled();
    // The legacy switches above answer to their own `saving` state, not this
    // one - they must not go dark for a request they have nothing to do with.
    expect(screen.getByRole("switch", { name: "Budget alerts" })).not.toBeDisabled();
  });

  it("still names every email that cannot be switched off", () => {
    render(<NotificationsSettingsPage />);

    // Mirrors the senders on EmailService: welcome (also used for the sign-in
    // link), password reset and organization invitation.
    expect(screen.getByText("Welcome")).toBeInTheDocument();
    expect(screen.getByText("Password reset")).toBeInTheDocument();
    expect(screen.getByText("Organization invitation")).toBeInTheDocument();
    expect(screen.getAllByText(/Not optional/)).toHaveLength(3);
  });

  it("claims no category this deployment has no sender for", () => {
    render(<NotificationsSettingsPage />);

    // The four categories the page used to meter, none of which had a sender.
    for (const absent of [
      /^Billing$/,
      /^Team activity$/,
      /^Security alerts$/,
      /^Product updates$/,
    ]) {
      expect(screen.queryByText(absent)).toBeNull();
    }
  });
});
