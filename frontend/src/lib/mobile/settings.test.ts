import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import { chooseMobileServer, parseMobileSettings, mobileSettings, setMobileLock } from "./settings";
const env = vi.hoisted(() => ({
  invoke: vi.fn(),
  iphone: vi.fn(),
  android: vi.fn(),
  disableIphone: vi.fn(),
  disableAndroid: vi.fn(),
}));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<object>()),
  invokeShell: env.invoke,
}));
vi.mock("./apns", () => ({ nativeIphonePush: env.iphone, disableIphonePush: env.disableIphone }));
vi.mock("./push", () => ({ phonePushStatus: env.android, disablePhonePush: env.disableAndroid }));
beforeEach(() => {
  vi.clearAllMocks();
});
describe("phone connections", () => {
  it("reads native settings and changes lock only through the native boundary", async () => {
    const value = {
      servers: [],
      active: null,
      locked_server: false,
      biometric_lock: true,
      biometric_managed: false,
      biometric_available: true,
    };
    env.invoke.mockResolvedValue(value);
    expect(await mobileSettings()).toEqual(value);
    expect(env.invoke).toHaveBeenLastCalledWith("mobile_settings");
    await setMobileLock(false);
    expect(env.invoke).toHaveBeenLastCalledWith("set_mobile_lock", { enabled: false });
  });
  it("rejects malformed native settings instead of inventing a protection state", () => {
    expect(() => parseMobileSettings({ servers: [], biometric_lock: "yes" })).toThrow();
    const valid = {
      servers: [{ name: "Work", url: "https://work.example/" }],
      active: "https://work.example/",
      locked_server: false,
      biometric_lock: true,
      biometric_managed: false,
      biometric_available: true,
    };
    expect(parseMobileSettings(valid)).toEqual(valid);
  });
  it("removes the current server's push registration before opening another connection", async () => {
    env.iphone.mockResolvedValue({ token: "a" });
    env.disableIphone.mockResolvedValue({ token: null });
    await chooseMobileServer("ios");
    expect(env.disableIphone).toHaveBeenCalledWith({ configured: true, token: "a" });
    expect(env.disableIphone.mock.invocationCallOrder[0]).toBeLessThan(
      env.invoke.mock.invocationCallOrder[0] ?? 0,
    );
    expect(env.invoke).toHaveBeenCalledWith("choose_server");
  });
  it("keeps the current connection if unregistering from the old server fails", async () => {
    env.android.mockResolvedValue({ subscription: { endpoint: "https://ntfy.sh/test" } });
    env.disableAndroid.mockRejectedValue(new ApiError(503, "offline"));
    await expect(chooseMobileServer("android")).rejects.toThrow();
    expect(env.invoke).not.toHaveBeenCalled();
  });
  it("opens the picker without unregistering when push was never enabled", async () => {
    env.android.mockResolvedValue({ subscription: null });
    await chooseMobileServer("android");
    expect(env.disableAndroid).not.toHaveBeenCalled();
    expect(env.invoke).toHaveBeenCalledWith("choose_server");
    env.iphone.mockResolvedValue({ token: null });
    await chooseMobileServer("ios");
    expect(env.disableIphone).not.toHaveBeenCalled();
  });
});
