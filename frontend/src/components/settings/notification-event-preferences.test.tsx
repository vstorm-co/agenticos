import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { NotificationEventPreferences } from "./notification-event-preferences";

const state = vi.hoisted(() => ({ loading: true }));
vi.mock("@/hooks", () => ({
  useNotificationPreferences: () => ({
    isEnabled: () => true,
    setPreference: vi.fn(),
    isLoading: state.loading,
    error: null,
    retry: vi.fn(),
  }),
}));

it("keeps event rows mounted while hiding unresolved preference controls", () => {
  const { container, rerender } = render(<NotificationEventPreferences />);
  const rows = Array.from(container.querySelectorAll("li"));
  expect(rows.length).toBeGreaterThan(0);
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  expect(container.querySelector("[inert]")).toHaveAttribute("aria-hidden", "true");
  state.loading = false;
  rerender(<NotificationEventPreferences />);
  expect(Array.from(container.querySelectorAll("li"))).toEqual(rows);
  expect(screen.getAllByRole("switch").length).toBeGreaterThan(0);
  expect(container.querySelector("[inert]")).not.toBeInTheDocument();
});
