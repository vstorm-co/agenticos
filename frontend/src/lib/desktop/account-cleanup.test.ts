import { afterEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth-store";
import { clearNativeAccount } from "./account-cleanup";
import { invokeShell, reportShellFailure } from "./shell";

vi.mock("./shell", async (original) => ({
  ...(await original<typeof import("./shell")>()),
  invokeShell: vi.fn().mockResolvedValue(null),
  reportShellFailure: vi.fn(),
}));

afterEach(async () => {
  await clearNativeAccount().catch(() => undefined);
  delete window.__AGENTICOS_SHELL__;
  vi.clearAllMocks();
});

it("does not invoke native commands in a browser", async () => {
  await clearNativeAccount();
  expect(invokeShell).not.toHaveBeenCalled();
});

it.each([
  ["ios", "clear_push_session"],
  ["android", "clear_push_session"],
  ["macos", "device_unlink"],
])("clears native identity on automatic session loss on %s", async (platform, command) => {
  window.__AGENTICOS_SHELL__ = { platform, version: "1.31.0", window: "main", vibrancy: false };
  useAuthStore.getState().setUser(null);
  await clearNativeAccount();
  expect(invokeShell).toHaveBeenCalledExactlyOnceWith(command);
});

it("shares pending cleanup with explicit logout and reports failures without retaining identity", async () => {
  window.__AGENTICOS_SHELL__ = {
    platform: "ios",
    version: "1.31.0",
    window: "main",
    vibrancy: false,
  };
  vi.mocked(invokeShell).mockRejectedValueOnce(new Error("native failure"));
  useAuthStore.getState().logout();
  await expect(clearNativeAccount()).rejects.toThrow("native failure");
  expect(invokeShell).toHaveBeenCalledTimes(1);
  expect(reportShellFailure).toHaveBeenCalledWith("session loss", expect.any(Error));
  expect(useAuthStore.getState().isAuthenticated).toBe(false);
  await clearNativeAccount();
  expect(invokeShell).toHaveBeenCalledTimes(2);
});
