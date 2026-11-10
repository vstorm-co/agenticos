import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { renderToString } from "react-dom/server";
import { DesktopSetupGate } from "./desktop-setup-gate";
import { OPEN_DESKTOP_SETUP } from "./desktop-setup-menu-item";

const env = vi.hoisted(() => ({
  reviewed: 1 as number | undefined,
  path: "/chat",
  key: "screen_capture",
  mark: vi.fn(),
}));
beforeEach(() => {
  env.reviewed = 1;
  env.path = "/chat";
  env.key = "screen_capture";
  env.mark.mockClear();
});

vi.mock("next/navigation", () => ({ usePathname: () => env.path }));
vi.mock("@/hooks/use-desktop-setup", () => ({
  useDesktopSetup: () => ({
    scope: "scope",
    revision: 1,
    items: [{ key: env.key, state: "missing" }],
    refresh: vi.fn(),
  }),
}));
vi.mock("@/hooks/use-desktop", () => ({ useShellEvent: vi.fn() }));
vi.mock("./readiness-panel", () => ({ ReadinessPanel: () => <p>Permission checklist</p> }));

it("does not offer a native checklist during server rendering", () => {
  expect(renderToString(<DesktopSetupGate />)).not.toContain("Permission checklist");
});
vi.mock("@/stores/desktop-preferences-store", () => ({
  useDesktopPreferencesStore: Object.assign(
    (select: (state: { reviewed: Record<string, number>; review: () => void }) => unknown) =>
      select({
        reviewed: env.reviewed === undefined ? {} : { scope: env.reviewed },
        review: env.mark,
      }),
    { persist: { onFinishHydration: () => () => {}, hasHydrated: () => true } },
  ),
}));

it("reopens a dismissed checklist directly, even when already on desktop settings", async () => {
  const user = userEvent.setup();
  render(<DesktopSetupGate />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByText(/setup items remaining/)).not.toBeInTheDocument();
  act(() => {
    window.dispatchEvent(new Event(OPEN_DESKTOP_SETUP));
  });
  expect(await screen.findByRole("dialog")).toHaveTextContent("Permission checklist");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("does not interrupt a new text user for optional system permissions", () => {
  env.reviewed = undefined;
  render(<DesktopSetupGate />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(env.mark).toHaveBeenCalledWith("scope", 1);
});
it("still offers repair when a required connection fact is missing", async () => {
  env.reviewed = undefined;
  env.key = "account";
  render(<DesktopSetupGate />);
  expect(await screen.findByRole("dialog")).toHaveTextContent("Permission checklist");
});

it("lets an invitation finish before offering connection repair", () => {
  env.reviewed = undefined;
  env.key = "device";
  env.path = "/pl/invitations/pending";
  render(<DesktopSetupGate />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
