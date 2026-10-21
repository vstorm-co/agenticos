import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PushSettings } from "./push-settings";

const env = vi.hoisted(() => ({
  shell: null as unknown,
  state: vi.fn(async (): Promise<string> => "off"),
  enable: vi.fn(async (): Promise<string> => "on"),
  disable: vi.fn(async (): Promise<string> => "off"),
  test: vi.fn(async () => ({ sent: 1, gone: 0, failed: 0 })),
  success: vi.fn(),
  error: vi.fn(),
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/lib/web-push", () => ({
  pushState: env.state,
  enablePush: env.enable,
  disablePush: env.disable,
  sendTestPush: env.test,
}));
vi.mock("sonner", () => ({ toast: { success: env.success, error: env.error } }));

beforeEach(() => {
  vi.clearAllMocks();
  env.shell = null;
  env.state.mockImplementation(async () => "off");
});

describe("PushSettings", () => {
  it("is not offered inside the desktop or phone app", () => {
    env.shell = { platform: "macos", version: "0.2.0", window: "main", vibrancy: true };
    const { container } = render(<PushSettings />);
    expect(container).toBeEmptyDOMElement();
    expect(env.state).not.toHaveBeenCalled();
  });

  it("turns push on, sends a test, and turns it off", async () => {
    render(<PushSettings />);
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    expect(env.enable).toHaveBeenCalled();
    await userEvent.click(await screen.findByRole("button", { name: "Send a test" }));
    expect(env.success).toHaveBeenCalledWith("Sent. It should appear in a moment.");
    env.test.mockResolvedValueOnce({ sent: 0, gone: 1, failed: 0 });
    await userEvent.click(screen.getByRole("button", { name: "Send a test" }));
    expect(env.error).toHaveBeenCalledWith(expect.stringContaining("did not take the test"));
    await userEvent.click(screen.getByRole("button", { name: "Turn off in this browser" }));
    expect(await screen.findByRole("button", { name: "Turn on" })).toBeInTheDocument();
  });

  it("says why a browser cannot, or will not, take push", async () => {
    env.state.mockImplementation(async () => "blocked");
    const { unmount } = render(<PushSettings />);
    expect(await screen.findByText(/blocks notifications/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    unmount();
    env.state.mockImplementation(async () => "unsupported");
    render(<PushSettings />);
    expect(await screen.findByText(/add AgenticOS to the Home Screen/)).toBeInTheDocument();
  });

  it("shows a failure, and treats an unreadable state as off", async () => {
    env.state.mockRejectedValueOnce(new Error("no"));
    env.enable.mockRejectedValueOnce(new Error("denied"));
    render(<PushSettings />);
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(env.error).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Turn on" })).not.toBeDisabled();
  });

  it("forgets a read that lands after it is gone", async () => {
    let resolve: (state: string) => void = () => {};
    env.state.mockImplementation(() => new Promise((done) => (resolve = done)));
    const { unmount } = render(<PushSettings />);
    unmount();
    resolve("on");
    env.state.mockImplementation(() => Promise.reject(new Error("late")));
    const again = render(<PushSettings />);
    again.unmount();
  });
});
