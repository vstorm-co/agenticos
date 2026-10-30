import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IphonePush as IphonePushState } from "@/lib/mobile/apns";

import { IphonePush } from "./iphone-push";

const push = (over: Partial<IphonePushState> = {}): IphonePushState => ({
  configured: true,
  permission: "undetermined",
  token: null,
  ...over,
});

const env = vi.hoisted(() => ({
  invoke: vi.fn().mockResolvedValue(null),
  read: vi.fn(),
  enable: vi.fn(),
  disable: vi.fn(),
  test: vi.fn(async () => ({ sent: 1, gone: 0, failed: 0 })),
  success: vi.fn(),
  error: vi.fn(),
}));
vi.mock("@/lib/mobile/apns", () => ({
  iphonePush: env.read,
  enableIphonePush: env.enable,
  disableIphonePush: env.disable,
}));
vi.mock("@/lib/web-push", () => ({ sendTestPush: env.test }));
vi.mock("sonner", () => ({ toast: { success: env.success, error: env.error } }));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  invokeShell: env.invoke,
}));

beforeEach(() => {
  vi.clearAllMocks();
  env.read.mockResolvedValue(push());
});

describe("IphonePush", () => {
  it("says an administrator has to add the key first", async () => {
    env.read.mockResolvedValue(push({ configured: false }));
    render(<IphonePush />);
    expect(await screen.findByText(/has not set up iPhone notifications/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says where to allow them when iOS has them off", async () => {
    env.read.mockResolvedValue(push({ permission: "denied" }));
    render(<IphonePush />);
    expect(await screen.findByText(/Settings, Notifications, AgenticOS/)).toBeInTheDocument();
  });

  it("turns push on, tests it and turns it off", async () => {
    env.enable.mockResolvedValue(push({ permission: "granted", token: "ab" }));
    env.disable.mockResolvedValue(push({ permission: "granted" }));
    render(<IphonePush />);
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    expect(await screen.findByText(/On for this iPhone/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Send a test" }));
    expect(env.success).toHaveBeenCalled();
    env.test.mockResolvedValueOnce({ sent: 0, gone: 0, failed: 1 });
    await userEvent.click(screen.getByRole("button", { name: "Send a test" }));
    expect(env.error).toHaveBeenCalledWith(expect.stringContaining("did not take the test"));
    await userEvent.click(screen.getByRole("button", { name: "Turn off on this iPhone" }));
    expect(await screen.findByRole("button", { name: "Turn on" })).toBeInTheDocument();
  });

  it("says so when the person said no to the system's question", async () => {
    env.enable.mockResolvedValue(push({ permission: "denied" }));
    render(<IphonePush />);
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    expect(env.error).toHaveBeenCalledWith(expect.stringContaining("Notifications are off"));
  });

  it("shows a failure to read or to act, and forgets a read after it is gone", async () => {
    env.read.mockRejectedValueOnce(new Error("no shell"));
    const { unmount } = render(<IphonePush />);
    await waitFor(() => expect(env.error).toHaveBeenCalled());
    unmount();
    let resolve: (value: IphonePushState) => void = () => {};
    env.read.mockImplementationOnce(() => new Promise((done) => (resolve = done)));
    const late = render(<IphonePush />);
    late.unmount();
    resolve(push());
    env.enable.mockRejectedValueOnce(new Error("refused"));
    render(<IphonePush />);
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(env.error).toHaveBeenCalledTimes(2));
  });
});

it("retries a failed permission read, opens system settings and refreshes on return", async () => {
  env.read.mockRejectedValueOnce(new Error("offline"));
  const view = render(<IphonePush />);
  env.read.mockResolvedValue(push({ permission: "denied" }));
  await userEvent.click(await screen.findByRole("button", { name: "Check again" }));
  await userEvent.click(await screen.findByRole("button", { name: "Open system settings" }));
  expect(env.invoke).toHaveBeenCalledWith("open_mobile_settings");
  const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  const reads = env.read.mock.calls.length;
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
  expect(env.read).toHaveBeenCalledTimes(reads + 1);
  visibility.mockRestore();
  view.unmount();
});
