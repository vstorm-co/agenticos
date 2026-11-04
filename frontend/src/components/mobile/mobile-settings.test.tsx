import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { MobileSettingsPanel } from "./mobile-settings";
import type { MobileSettings } from "@/lib/mobile/settings";
const env = vi.hoisted(() => ({
  shell: { platform: "ios" } as { platform: string } | null,
  read: vi.fn(),
  lock: vi.fn(),
  choose: vi.fn(),
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/lib/mobile/settings", () => ({
  mobileSettings: env.read,
  setMobileLock: env.lock,
  chooseMobileServer: env.choose,
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
const ready: MobileSettings = {
  active: "https://work.example/",
  servers: [{ url: "https://work.example/", name: "Work" }],
  biometric_available: true,
  biometric_managed: false,
  biometric_lock: false,
  locked_server: false,
};
const show = () =>
  render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
      }
    >
      <MobileSettingsPanel />
    </QueryClientProvider>,
  );
beforeEach(() => {
  vi.clearAllMocks();
  env.shell = { platform: "ios" };
  env.read.mockResolvedValue(ready);
  env.lock.mockResolvedValue(undefined);
  env.choose.mockResolvedValue(undefined);
});
it("shows actual settings, changes lock and switches only after native cleanup", async () => {
  const user = userEvent.setup();
  show();
  expect(await screen.findByText("Work")).toBeVisible();
  await user.click(screen.getByRole("switch", { name: "App lock" }));
  expect(env.lock.mock.calls[0]?.[0]).toBe(true);
  await user.click(screen.getByRole("button", { name: "Switch server" }));
  expect(env.choose).toHaveBeenCalledWith("ios");
});
it("keeps managed or unavailable biometrics disabled and falls back to the saved address", async () => {
  env.read.mockResolvedValue({
    ...ready,
    servers: [],
    biometric_managed: true,
    locked_server: true,
  });
  const first = show();
  expect(await screen.findByRole("switch")).toBeDisabled();
  expect(screen.getByText("Managed by your organization")).toBeVisible();
  expect(screen.getByRole("button", { name: "Switch server" })).toBeDisabled();
  first.unmount();
  env.read.mockResolvedValue({ ...ready, biometric_available: false });
  show();
  expect(await screen.findByText("Not available on this device")).toBeVisible();
  expect(screen.getByRole("switch")).toBeDisabled();
});
it("offers retry for unreadable settings and surfaces native refusals", async () => {
  const user = userEvent.setup();
  env.read.mockRejectedValueOnce(new Error("offline"));
  show();
  await user.click(await screen.findByRole("button", { name: "Check again" }));
  expect(await screen.findByText("Work")).toBeVisible();
  env.lock.mockRejectedValueOnce(new Error("denied"));
  await user.click(screen.getByRole("switch"));
  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith("Could not update this setting. Try again."),
  );
  env.choose.mockRejectedValueOnce(new Error("offline"));
  await user.click(screen.getByRole("button", { name: "Switch server" }));
  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Could not switch")),
  );
});
it("has no phone controls in a browser", () => {
  env.shell = null;
  show();
  expect(screen.queryByRole("switch")).toBeNull();
});
