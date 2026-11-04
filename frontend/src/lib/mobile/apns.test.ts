import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";

import {
  apnsSetup,
  clearApnsKey,
  disableIphonePush,
  enableIphonePush,
  iphonePush,
  parseApnsStatus,
  setApnsKey,
  syncIphonePush,
} from "./apns";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));
vi.mock("@/lib/api-client", () => ({ apiClient: api }));

const TOKEN = "ab".repeat(32);

it("accepts an already removed registration but preserves a failed server cleanup", async () => {
  const push = { configured: true, permission: "granted" as const, token: TOKEN };
  api.delete.mockRejectedValueOnce(new ApiError(404, "gone"));
  await expect(disableIphonePush(push)).resolves.toMatchObject({ token: null });
  api.delete.mockRejectedValueOnce(new ApiError(503, "offline"));
  await expect(disableIphonePush(push)).rejects.toThrow("offline");
  api.delete.mockRejectedValueOnce(new Error("network"));
  await expect(disableIphonePush(push)).rejects.toThrow("network");
});
const invoke = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  window.__TAURI__ = { core: { invoke }, event: { listen: vi.fn() } };
  api.get.mockResolvedValue({ configured: true });
});

afterEach(() => {
  delete window.__TAURI__;
});

describe("the iPhone's push", () => {
  it("reads the app's answer and refuses one in another shape", () => {
    expect(parseApnsStatus({ permission: "granted", token: TOKEN })).toEqual({
      permission: "granted",
      token: TOKEN,
    });
    expect(parseApnsStatus({ permission: "undetermined" })).toEqual({
      permission: "undetermined",
      token: null,
    });
    for (const broken of [null, { permission: "maybe" }, { permission: "granted", token: 1 }]) {
      expect(() => parseApnsStatus(broken)).toThrow();
    }
  });

  it("says whether the organization set a key, with what the app answers", async () => {
    invoke.mockResolvedValue({ permission: "denied" });
    expect(await iphonePush()).toEqual({ configured: true, permission: "denied", token: null });
    expect(api.get).toHaveBeenCalledWith("/push/apns");
    expect(invoke).toHaveBeenCalledWith("apns_status", undefined);
  });

  it("tells the server a granted iPhone's token, and nothing else", async () => {
    await syncIphonePush({ configured: false, permission: "granted", token: TOKEN });
    await syncIphonePush({ configured: true, permission: "denied", token: TOKEN });
    await syncIphonePush({ configured: true, permission: "granted", token: null });
    expect(api.post).not.toHaveBeenCalled();
    await syncIphonePush({ configured: true, permission: "granted", token: TOKEN });
    expect(api.post).toHaveBeenCalledWith("/push/apns/devices", { token: TOKEN });
  });

  it("registers, then forgets it on the server and in the app", async () => {
    invoke.mockResolvedValueOnce({ permission: "granted", token: TOKEN });
    const on = await enableIphonePush();
    expect(on.token).toBe(TOKEN);
    expect(invoke).toHaveBeenCalledWith("apns_register", undefined);
    expect(api.post).toHaveBeenCalledWith("/push/apns/devices", { token: TOKEN });
    expect(await disableIphonePush(on)).toEqual({ ...on, token: null });
    expect(api.delete).toHaveBeenCalledWith("/push/apns/devices", { params: { token: TOKEN } });
    expect(invoke).toHaveBeenLastCalledWith("apns_unregister", undefined);
    api.delete.mockClear();
    await disableIphonePush({ ...on, token: null });
    expect(api.delete).not.toHaveBeenCalled();
  });
});

describe("the organization's key", () => {
  it("is read, set and cleared through the push routes", async () => {
    await apnsSetup();
    const key = {
      key_id: "KEY1234567",
      team_id: "TEAM123456",
      topic: "com.acme.app",
      environment: "production" as const,
      private_key: "the contents of AuthKey_KEY1234567.p8",
    };
    await setApnsKey(key);
    await clearApnsKey();
    expect(api.put).toHaveBeenCalledWith("/push/apns", key);
    expect(api.delete).toHaveBeenCalledWith("/push/apns");
  });
});
