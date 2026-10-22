import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DESKTOP_STATE, MAC_MAIN } from "@/components/desktop/fixtures";
import { PinAgentButton } from "./pin-agent-button";

const AGENT = {
  id: "00000000-0000-4000-8000-000000000001",
  name: "Support",
  slug: "support",
  hasAvatar: false,
  colorSlot: null,
};
const PHONE = { platform: "android", version: "0.1.0", window: "main", vibrancy: false };

const env = vi.hoisted(() => ({
  shell: null as unknown,
  state: undefined as unknown,
  change: { mutate: vi.fn(), isPending: false },
  pinToHomeScreen: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  report: vi.fn(),
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-desktop", () => ({
  useDesktopState: () => ({ data: env.state }),
  useSetPinned: () => env.change,
}));
vi.mock("@/lib/mobile/pin", () => ({ pinToHomeScreen: env.pinToHomeScreen }));
vi.mock("sonner", () => ({ toast: { success: env.success, error: env.error } }));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  reportShellFailure: env.report,
}));

beforeEach(() => {
  vi.clearAllMocks();
  env.shell = MAC_MAIN;
  env.state = DESKTOP_STATE;
});

describe("PinAgentButton", () => {
  it("is nothing in a browser, or in another of the desktop app's windows", () => {
    env.shell = null;
    const browser = render(<PinAgentButton agent={AGENT} />);
    expect(browser.container).toBeEmptyDOMElement();
    browser.unmount();

    env.shell = { ...MAC_MAIN, window: "quick-ask" };
    expect(render(<PinAgentButton agent={AGENT} />).container).toBeEmptyDOMElement();
  });

  it("pins the agent to the Dock on a Mac, and unpins one already there", async () => {
    const { rerender } = render(<PinAgentButton agent={AGENT} />);
    await userEvent.click(screen.getByRole("button", { name: "Pin to Dock" }));
    expect(env.change.mutate).toHaveBeenCalledWith({
      agent: { id: AGENT.id, name: "Support" },
      pinned: true,
    });

    env.state = { ...DESKTOP_STATE, pinned: [{ id: AGENT.id, name: "Support" }] };
    rerender(<PinAgentButton agent={AGENT} />);
    await userEvent.click(screen.getByRole("button", { name: "Unpin" }));
    expect(env.change.mutate).toHaveBeenLastCalledWith({
      agent: { id: AGENT.id, name: "Support" },
      pinned: false,
    });
  });

  it("names the tray elsewhere, and waits for the app's state and a published agent", () => {
    env.shell = { ...MAC_MAIN, platform: "linux" };
    const { rerender } = render(<PinAgentButton agent={AGENT} disabled />);
    expect(screen.getByRole("button", { name: "Pin to tray" })).toBeDisabled();

    env.state = undefined;
    rerender(<PinAgentButton agent={AGENT} />);
    expect(screen.getByRole("button", { name: "Pin to tray" })).toBeDisabled();
  });

  it("adds the agent to a phone's home screen, or says where it went instead", async () => {
    env.shell = PHONE;
    env.pinToHomeScreen.mockResolvedValueOnce(true).mockResolvedValueOnce(false);
    render(<PinAgentButton agent={AGENT} />);
    const button = screen.getByRole("button", { name: "Add to home screen" });

    await userEvent.click(button);
    expect(env.pinToHomeScreen).toHaveBeenCalledWith(AGENT);
    expect(env.success).toHaveBeenLastCalledWith(expect.stringContaining("home screen"));

    await userEvent.click(button);
    expect(env.success).toHaveBeenLastCalledWith(expect.stringContaining("long-press"));
  });

  it("says when the phone could not add it", async () => {
    env.shell = PHONE;
    env.pinToHomeScreen.mockRejectedValueOnce(new Error("no launcher"));
    render(<PinAgentButton agent={AGENT} />);

    await userEvent.click(screen.getByRole("button", { name: "Add to home screen" }));

    expect(env.error).toHaveBeenCalled();
    expect(env.report).toHaveBeenCalledWith(
      "could not pin an agent to the home screen",
      expect.any(Error),
    );
  });
});
