import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { DesktopSetupGate } from "./desktop-setup-gate";
import { OPEN_DESKTOP_SETUP } from "./desktop-setup-menu-item";

vi.mock("@/hooks/use-desktop-setup", () => ({
  useDesktopSetup: () => ({
    scope: "scope",
    revision: 1,
    items: [{ key: "screen", state: "missing" }],
    refresh: vi.fn(),
  }),
}));
vi.mock("@/hooks/use-desktop", () => ({ useShellEvent: vi.fn() }));
vi.mock("./readiness-panel", () => ({ ReadinessPanel: () => <p>Permission checklist</p> }));
vi.mock("@/stores/desktop-preferences-store", () => ({
  useDesktopPreferencesStore: Object.assign(
    (select: (state: { reviewed: Record<string, number>; review: () => void }) => unknown) =>
      select({ reviewed: { scope: 1 }, review: () => {} }),
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
