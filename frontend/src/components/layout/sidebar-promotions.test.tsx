import Link from "next/link";
import type { ComponentProps } from "react";
import { renderToString } from "react-dom/server";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SidebarPromotions } from "./sidebar-promotions";
vi.mock("next/link", () => ({
  default: ({ children, ...props }: ComponentProps<"a">) => <a {...props}>{children}</a>,
}));
const env = vi.hoisted(() => ({ setup: true, desktop: true, reduced: false, dismiss: vi.fn() }));
vi.mock("@/components/onboarding/onboarding-reminder", () => ({
  useOnboardingReminder: () => ({ eligible: env.setup }),
  OnboardingReminderCard: ({
    collapsed,
    onNavigate,
  }: {
    collapsed?: boolean;
    onNavigate?: () => void;
  }) => (
    <Link href="/onboarding" onClick={onNavigate}>
      {collapsed ? "Setup rail" : "Finish setup"}
    </Link>
  ),
}));
vi.mock("./desktop-install-prompt", () => ({
  useDesktopInstallPrompt: () => ({ eligible: env.desktop, dismiss: env.dismiss }),
  DesktopInstallCard: ({ dismiss }: { dismiss: () => void }) => (
    <button onClick={dismiss}>Desktop app</button>
  ),
}));
vi.mock("@/hooks/use-reduced-motion", () => ({ useReducedMotion: () => env.reduced }));
let intersect: (entries: { isIntersecting: boolean }[]) => void;
const disconnect = vi.fn();
beforeEach(() => {
  env.setup = true;
  env.desktop = true;
  env.reduced = false;
  vi.useFakeTimers();
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.stubGlobal(
    "IntersectionObserver",
    vi.fn(function (callback: typeof intersect) {
      intersect = callback;
      return { observe: () => callback([{ isIntersecting: true }]), disconnect };
    }),
  );
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function advance() {
  act(() => vi.advanceTimersByTime(8000));
}
it("alternates only eligible cards and preserves each action", () => {
  render(<SidebarPromotions />);
  expect(screen.getByRole("link", { name: "Finish setup" })).toBeVisible();
  advance();
  fireEvent.click(screen.getByRole("button", { name: "Desktop app" }));
  expect(env.dismiss).toHaveBeenCalledOnce();
  advance();
  // Focus has not moved: a synthetic click alone does not request a pause.
  expect(screen.getByRole("link", { name: "Finish setup" })).toBeVisible();
});
it("offers manual navigation without restarting automatic rotation", () => {
  render(<SidebarPromotions />);
  fireEvent.click(screen.getByRole("button", { name: "Next card" }));
  advance();
  expect(screen.getByRole("button", { name: "Desktop app" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Previous card" }));
  expect(screen.getByRole("link", { name: "Finish setup" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Resume rotation" }));
  advance();
  expect(screen.getByRole("button", { name: "Desktop app" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Pause rotation" }));
  advance();
  expect(screen.getByRole("button", { name: "Desktop app" })).toBeVisible();
});
it("pauses on hover and keyboard focus, requiring explicit resume after focus", () => {
  render(<SidebarPromotions />);
  const region = screen.getByRole("region", { name: "Getting started" });
  fireEvent.mouseEnter(region);
  advance();
  expect(screen.getByRole("link")).toBeVisible();
  fireEvent.mouseLeave(region);
  advance();
  expect(screen.getByRole("button", { name: "Desktop app" })).toBeVisible();
  const next = screen.getByRole("button", { name: "Next card" });
  fireEvent.focus(next);
  advance();
  fireEvent.blur(next, { relatedTarget: screen.getByRole("button", { name: "Previous card" }) });
  advance();
  fireEvent.blur(next, { relatedTarget: null });
  advance();
  expect(screen.getByRole("button", { name: "Desktop app" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Resume rotation" }));
  advance();
  expect(screen.getByRole("link")).toBeVisible();
});
it("never auto-turns with reduced motion but retains manual controls", () => {
  env.reduced = true;
  render(<SidebarPromotions />);
  advance();
  expect(screen.getByRole("link")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Pause rotation" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Next card" }));
  expect(screen.getByRole("button", { name: "Desktop app" })).toBeVisible();
});
it("stops when the page or card is not visible and cleans up its observer/timer", () => {
  const view = render(<SidebarPromotions />);
  act(() => intersect([{ isIntersecting: false }]));
  advance();
  expect(screen.getByRole("link")).toBeVisible();
  act(() => intersect([{ isIntersecting: true }]));
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  fireEvent(document, new Event("visibilitychange"));
  advance();
  expect(screen.getByRole("link")).toBeVisible();
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  fireEvent(document, new Event("visibilitychange"));
  advance();
  expect(screen.getByRole("button", { name: "Desktop app" })).toBeVisible();
  view.unmount();
  expect(disconnect).toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});
it("does not resurrect snoozed or completed setup, or a dismissed desktop invitation", () => {
  const view = render(<SidebarPromotions />);
  env.setup = false;
  view.rerender(<SidebarPromotions />);
  expect(screen.queryByRole("link")).toBeNull();
  expect(screen.queryByRole("button", { name: "Next card" })).toBeNull();
  env.desktop = false;
  view.rerender(<SidebarPromotions />);
  expect(screen.queryByRole("button")).toBeNull();
  env.setup = true;
  view.rerender(<SidebarPromotions />);
  expect(screen.getByRole("link")).toBeVisible();
});
it("keeps only the existing setup shortcut on the collapsed rail", () => {
  const navigate = vi.fn();
  const view = render(<SidebarPromotions collapsed onNavigate={navigate} />);
  fireEvent.click(screen.getByRole("link", { name: "Setup rail" }));
  expect(navigate).toHaveBeenCalledOnce();
  expect(screen.queryByRole("region")).toBeNull();
  env.setup = false;
  view.rerender(<SidebarPromotions collapsed />);
  expect(screen.queryByRole("link")).toBeNull();
});

it("renders the same first card without starting timers on the server", () => {
  expect(renderToString(<SidebarPromotions />)).toContain("Finish setup");
  expect(vi.getTimerCount()).toBe(0);
});
