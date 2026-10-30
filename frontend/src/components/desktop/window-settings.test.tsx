import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DESKTOP_STATE, MAC_MAIN } from "./fixtures";
import { WindowSettings } from "./window-settings";

const change = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false }));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => MAC_MAIN }));
vi.mock("@/hooks/use-desktop", () => ({
  useDesktopState: () => ({ data: DESKTOP_STATE, error: null }),
  useSetWindowPreferences: () => change,
}));

describe("WindowSettings", () => {
  it("shows each preference and changes one, keeping the others", async () => {
    render(<WindowSettings />);
    expect(
      screen.getByRole("switch", { name: "Keep running when the window is closed" }),
    ).toBeChecked();
    expect(screen.getByRole("switch", { name: "Open at login" })).not.toBeChecked();

    await userEvent.click(screen.getByRole("switch", { name: "Open at login" }));

    expect(change.mutate).toHaveBeenCalledWith({ ...DESKTOP_STATE.window, launch_at_login: true });
  });
});
