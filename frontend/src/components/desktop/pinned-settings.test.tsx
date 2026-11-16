import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DESKTOP_STATE, MAC_MAIN } from "./fixtures";
import { PinnedSettings } from "./pinned-settings";

const SUPPORT = { id: "00000000-0000-4000-8000-000000000001", name: "Support" };
const env = vi.hoisted(() => ({
  shell: null as unknown,
  pinned: [] as { id: string; name: string }[],
  change: { mutate: vi.fn(), isPending: false },
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-desktop", () => ({
  useDesktopState: () => ({ data: { ...DESKTOP_STATE, pinned: env.pinned }, error: null }),
  useSetPinned: () => env.change,
}));

beforeEach(() => {
  env.shell = MAC_MAIN;
  env.pinned = [];
  env.change.mutate.mockClear();
});

describe("PinnedSettings", () => {
  it("says where pinning is done while nothing is pinned", async () => {
    render(<PinnedSettings />);
    expect(screen.getByText(/No agents pinned yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "More information" }));
    expect(screen.getByText(/Dock icon's menu/)).toBeInTheDocument();
  });

  it("lists the pinned agents and takes one off", async () => {
    env.pinned = [SUPPORT];
    render(<PinnedSettings />);

    await userEvent.click(screen.getByRole("button", { name: "Unpin" }));

    expect(screen.getByText("Support")).toBeInTheDocument();
    expect(env.change.mutate).toHaveBeenCalledWith({ agent: SUPPORT, pinned: false });
  });

  it("names the tray on Windows and Linux", async () => {
    env.shell = { ...MAC_MAIN, platform: "windows" };
    render(<PinnedSettings />);
    await userEvent.click(screen.getByRole("button", { name: "More information" }));
    expect(screen.getByText(/tray icon's menu/)).toBeInTheDocument();
  });
});
