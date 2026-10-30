import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PhonePushStatus } from "@/lib/mobile/push";

import { PhonePush } from "./phone-push";

const status = (over: Partial<PhonePushStatus> = {}): PhonePushStatus => ({
  distributors: ["io.heckel.ntfy"],
  distributor: "ntfy",
  failed: null,
  subscription: null,
  ...over,
});
const SUBSCRIPTION = { endpoint: "https://ntfy.sh/upX", keys: { p256dh: "a", auth: "b" } };

const env = vi.hoisted(() => ({
  invoke: vi.fn().mockResolvedValue(null),
  read: vi.fn(),
  enable: vi.fn(),
  disable: vi.fn(),
  test: vi.fn(async () => ({ sent: 1, gone: 0, failed: 0 })),
  success: vi.fn(),
  error: vi.fn(),
}));
vi.mock("@/lib/mobile/push", () => ({
  phonePushStatus: env.read,
  enablePhonePush: env.enable,
  disablePhonePush: env.disable,
}));
vi.mock("@/lib/web-push", () => ({ sendTestPush: env.test }));
vi.mock("sonner", () => ({ toast: { success: env.success, error: env.error } }));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  invokeShell: env.invoke,
}));

beforeEach(() => {
  vi.clearAllMocks();
  env.read.mockResolvedValue(status());
});

describe("PhonePush", () => {
  it("says what to install when the phone has no distributor", async () => {
    env.read.mockResolvedValue(status({ distributors: [], distributor: null }));
    render(<PhonePush />);
    expect(await screen.findByText(/AgenticOS delivers these through ntfy/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Install ntfy" })).toHaveAttribute(
      "href",
      "https://ntfy.sh/docs/subscribe/phone/",
    );
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
  });

  it("turns push on, tests it and turns it off", async () => {
    env.enable.mockResolvedValue(status({ subscription: SUBSCRIPTION }));
    env.disable.mockResolvedValue(status());
    render(<PhonePush />);
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    expect(await screen.findByText(/On, through ntfy/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Send a test" }));
    expect(env.success).toHaveBeenCalled();
    env.test.mockResolvedValueOnce({ sent: 0, gone: 0, failed: 1 });
    await userEvent.click(screen.getByRole("button", { name: "Send a test" }));
    expect(env.error).toHaveBeenCalledWith(expect.stringContaining("did not take the test"));
    await userEvent.click(screen.getByRole("button", { name: "Turn off on this phone" }));
    expect(await screen.findByRole("button", { name: "Turn on" })).toBeInTheDocument();
  });

  it("says when the distributor handed nothing over, or failed before", async () => {
    env.enable.mockResolvedValue(status({ failed: "NETWORK" }));
    render(<PhonePush />);
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    expect(env.error).toHaveBeenCalledWith(expect.stringContaining("did not hand over"));
    expect(await screen.findByText(/did not take the registration/)).toBeInTheDocument();
  });

  it("shows a failure to read or to act, and forgets a read after it is gone", async () => {
    env.read.mockRejectedValueOnce(new Error("no shell"));
    const { unmount } = render(<PhonePush />);
    await waitFor(() => expect(env.error).toHaveBeenCalled());
    unmount();
    let resolve: (value: PhonePushStatus) => void = () => {};
    env.read.mockImplementationOnce(() => new Promise((done) => (resolve = done)));
    const late = render(<PhonePush />);
    late.unmount();
    resolve(status());
    env.enable.mockRejectedValueOnce(new Error("refused"));
    render(<PhonePush />);
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(env.error).toHaveBeenCalledTimes(2));
  });
});

it("retries unreadable permissions, opens system settings and refreshes on return", async () => {
  env.read.mockRejectedValueOnce(new Error("offline"));
  const view = render(<PhonePush />);
  env.read.mockResolvedValue(status({ permission: "denied" }));
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
  env.read.mockResolvedValue(status({ distributors: [], distributor: null }));
  render(<PhonePush />);
  await userEvent.click(await screen.findByRole("button", { name: "Check again" }));
  expect(env.read.mock.calls.length).toBeGreaterThan(reads + 1);
});
