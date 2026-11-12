import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { DESKTOP_STATE, MAC_MAIN } from "@/components/desktop/fixtures";

import DesktopAppPage from "./page";

const env = vi.hoisted(() => ({ shell: null as unknown, stateError: null as Error | null }));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-desktop", () => ({
  useDesktopState: () =>
    env.stateError
      ? { data: undefined, error: env.stateError }
      : { data: DESKTOP_STATE, error: null },
}));
vi.mock("@/components/desktop/readiness-panel", () => ({
  ReadinessPanel: () => <p>readiness</p>,
}));
vi.mock("@/components/desktop/notification-settings", () => ({
  DesktopNotificationSettings: () => <p>notifications</p>,
}));
vi.mock("@/components/desktop/device-settings", () => ({ DeviceSettings: () => <p>device</p> }));
vi.mock("@/components/desktop/window-settings", () => ({ WindowSettings: () => <p>window</p> }));
vi.mock("@/components/desktop/pinned-settings", () => ({ PinnedSettings: () => <p>pinned</p> }));

const SECTIONS = ["readiness", "notifications", "device", "window", "pinned"];

beforeEach(() => {
  env.shell = null;
  env.stateError = null;
});

it("says once, in a browser, that these settings belong to the desktop app", () => {
  render(<DesktopAppPage />);
  expect(screen.getAllByText("These settings belong to the AgenticOS desktop app.")).toHaveLength(
    1,
  );
  for (const section of SECTIONS) expect(screen.queryByText(section)).toBeNull();
});

it("shows every section inside the app", () => {
  env.shell = MAC_MAIN;
  render(<DesktopAppPage />);
  for (const section of SECTIONS) expect(screen.getByText(section)).toBeInTheDocument();
});

it("still shows readiness and notifications inside the app when its state cannot be read", () => {
  env.shell = MAC_MAIN;
  env.stateError = new Error("malformed");
  render(<DesktopAppPage />);
  expect(screen.getByText("readiness")).toBeInTheDocument();
  expect(screen.getByText("notifications")).toBeInTheDocument();
});
