import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DesktopInstallPrompt } from "./desktop-install-prompt";
import { useAuthStore } from "@/stores";

const env = vi.hoisted(() => ({ native: false }));
vi.mock("@/hooks/use-shell", () => ({
  useShell: () => (env.native ? { platform: "macos" } : null),
}));
beforeEach(() => {
  localStorage.clear();
  env.native = false;
  vi.stubGlobal("navigator", { userAgent: "Macintosh", maxTouchPoints: 0 });
  useAuthStore.setState({
    user: { id: "alice", email: "a@example.com", is_active: true, created_at: "2026-10-01" },
  });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
it("offers public desktop releases to a signed-in browser user", () => {
  render(<DesktopInstallPrompt />);
  expect(screen.getByRole("link", { name: "Get the desktop app" })).toHaveAttribute(
    "href",
    "https://github.com/vstorm-co/agenticos/releases/latest",
  );
});
it("keeps dismissal across remounts and offers it again after 14 days", () => {
  vi.useFakeTimers();
  const view = render(<DesktopInstallPrompt />);
  fireEvent.click(screen.getByRole("button", { name: "Remind me in 14 days" }));
  expect(screen.queryByRole("link")).toBeNull();
  view.unmount();
  render(<DesktopInstallPrompt />);
  expect(screen.queryByRole("link")).toBeNull();
  act(() => vi.advanceTimersByTime(14 * 24 * 60 * 60 * 1000 + 2));
  expect(screen.getByRole("link")).toBeInTheDocument();
});
it("does not transfer one account's dismissal to another", () => {
  render(<DesktopInstallPrompt />);
  fireEvent.click(screen.getByRole("button"));
  act(() =>
    useAuthStore.setState({
      user: { id: "bob", email: "b@example.com", is_active: true, created_at: "2026-10-01" },
    }),
  );
  expect(screen.getByRole("link")).toBeInTheDocument();
});
it("stays out of native apps and phone browsers", () => {
  env.native = true;
  const view = render(<DesktopInstallPrompt />);
  expect(screen.queryByRole("link")).toBeNull();
  env.native = false;
  vi.stubGlobal("navigator", { userAgent: "iPhone", maxTouchPoints: 5 });
  view.rerender(<DesktopInstallPrompt />);
  expect(screen.queryByRole("link")).toBeNull();
});
it("can still be dismissed if browser storage is unavailable", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("Blocked", "SecurityError");
  });
  render(<DesktopInstallPrompt />);
  fireEvent.click(screen.getByRole("button"));
  expect(screen.queryByRole("link")).toBeNull();
});
