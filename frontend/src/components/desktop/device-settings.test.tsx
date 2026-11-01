import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { DESKTOP_STATE, MAC_MAIN } from "./fixtures";
import { DeviceSettings } from "./device-settings";

const env = vi.hoisted(() => ({
  shell: { platform: "macos", version: "0.2.0", window: "main", vibrancy: true },
  status: { linked: false, connected: false },
  pending: false,
  link: vi.fn(),
  unlink: vi.fn(),
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-desktop", () => ({
  useDesktopState: () => ({ data: DESKTOP_STATE, error: null }),
  useDeviceStatus: () => ({ data: env.status }),
  useDeviceLink: () => ({
    link: { mutate: env.link, isPending: env.pending },
    unlink: { mutate: env.unlink, isPending: env.pending },
  }),
}));
vi.mock("./local-agent-settings", () => ({
  LocalAgentSettings: () => <div data-testid="agents" />,
}));
vi.mock("./local-service-settings", () => ({
  LocalServiceSettings: () => <div data-testid="services" />,
}));
beforeEach(() => {
  env.shell = MAC_MAIN;
  env.status = { linked: false, connected: false };
  env.pending = false;
  vi.clearAllMocks();
});
it("links only after the person chooses the action and waits for native consent", async () => {
  const view = render(<DeviceSettings />);
  const link = screen.getByRole("button", { name: "Let agents work here" });
  await userEvent.click(link);
  expect(env.link).toHaveBeenCalledOnce();
  env.pending = true;
  view.rerender(<DeviceSettings />);
  expect(screen.getByRole("button", { name: "Let agents work here" })).toBeDisabled();
  expect(screen.getByTestId("services")).toBeInTheDocument();
});
it("shows reconnecting and live states and disconnects the paired computer", async () => {
  env.status = { linked: true, connected: false };
  const view = render(<DeviceSettings />);
  expect(screen.getByText(/reconnecting/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Unlink" }));
  expect(env.unlink).toHaveBeenCalledOnce();
  env.status.connected = true;
  view.rerender(<DeviceSettings />);
  expect(screen.getByText("Live")).toBeInTheDocument();
});
it("offers desktop settings only in the desktop app", () => {
  env.shell = { ...MAC_MAIN, platform: "ios" };
  render(<DeviceSettings />);
  expect(screen.queryByTestId("services")).not.toBeInTheDocument();
});
