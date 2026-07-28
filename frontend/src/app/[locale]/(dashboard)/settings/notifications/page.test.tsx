import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NotificationsSettingsPage from "./page";

/**
 * The regression guard for a page that lied.
 *
 * `/settings/notifications` offered four category toggles across two channels
 * and a Save button that wrote to `localStorage` and raised a
 * "Notification preferences saved" toast. No notification-preference model
 * existed on the server, so nothing downstream of a toggle ever read it: the
 * email was sent regardless and the setting did not leave the browser.
 *
 * Pages in this project are normally left to the E2E suite, and this one is
 * deliberately excluded from the vitest coverage `include` for that reason - it
 * is not mounted here to move a number. It is mounted because the failure was
 * not a broken page but a *convincing* one, and the cheapest way to keep it
 * from coming back is to assert that no control on it claims to save anything.
 */

describe("the notifications settings page", () => {
  it("offers no control that claims to change what is sent", () => {
    render(<NotificationsSettingsPage />);

    // The bug itself: a switch and a save button over storage no sender reads.
    expect(screen.queryAllByRole("switch")).toEqual([]);
    expect(screen.queryAllByRole("button")).toEqual([]);
    expect(screen.queryByText(/save/i)).toBeNull();
  });

  it("writes nothing to local storage", () => {
    render(<NotificationsSettingsPage />);

    expect(localStorage.length).toBe(0);
  });

  it("names every email this deployment actually sends", () => {
    render(<NotificationsSettingsPage />);

    // Mirrors the senders on EmailService: welcome (also used for the sign-in
    // link), password reset and organization invitation.
    expect(screen.getByText("Welcome")).toBeInTheDocument();
    expect(screen.getByText("Password reset")).toBeInTheDocument();
    expect(screen.getByText("Organization invitation")).toBeInTheDocument();
  });

  it("claims no category this deployment has no sender for", () => {
    render(<NotificationsSettingsPage />);

    // The four categories the page used to meter. Billing and product updates
    // have no sender at all; the other two were names for nothing.
    for (const absent of [
      /^Billing$/,
      /^Team activity$/,
      /^Security alerts$/,
      /^Product updates$/,
    ]) {
      expect(screen.queryByText(absent)).toBeNull();
    }
  });

  it("says why each email cannot be switched off", () => {
    render(<NotificationsSettingsPage />);

    // Three emails, three stated reasons - a row without one is a row that
    // looks arbitrary, which is what invites a toggle back.
    expect(screen.getAllByText(/Not optional/)).toHaveLength(3);
  });
});
