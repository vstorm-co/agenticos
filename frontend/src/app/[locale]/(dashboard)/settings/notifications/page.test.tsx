import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NotificationsSettingsPage from "./page";
import { apiClient } from "@/lib/api-client";
import type { User } from "@/types";

/**
 * The guard for a page that once lied.
 *
 * `/settings/notifications` used to offer four toggles that saved to
 * `localStorage`, which no sender ever read. The toggles are back, but each
 * one now writes a `notify_*` column through PATCH `/users/me` that
 * `NotificationService` consults before sending - so what this file pins is
 * the page's half of that contract: a switch renders the stored value, a flip
 * sends exactly one field to the server, and nothing touches `localStorage`.
 */

vi.mock("@/lib/api-client", () => ({
  apiClient: { patch: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn() },
}));

const setUser = vi.fn();
let currentUser: Partial<User>;

vi.mock("@/hooks", () => ({
  useAuth: () => ({ user: currentUser }),
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
  });

  it("offers one switch per email the backend actually gates", () => {
    render(<NotificationsSettingsPage />);

    // Mirrors NotificationService: budget_exceeded, approval_requested,
    // usage_report. A fourth switch here means a sender was added without
    // wiring its preference, or a toggle was invented without a sender.
    expect(screen.getByRole("switch", { name: "Budget alerts" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Approval requests" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Usage reports" })).toBeInTheDocument();
    expect(screen.getAllByRole("switch")).toHaveLength(3);
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
