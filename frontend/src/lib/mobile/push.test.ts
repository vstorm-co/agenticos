import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ShellError } from "@/lib/desktop/shell";
import { ApiError } from "@/lib/api-error";

const api = vi.hoisted(() => ({
  get: vi.fn(async () => ({ public_key: "BPub" })),
  post: vi.fn(async () => undefined),
  delete: vi.fn(async () => undefined),
}));
vi.mock("@/lib/api-client", () => ({ apiClient: api }));

import { disablePhonePush, enablePhonePush, parsePhonePushStatus, syncPhonePush } from "./push";

const ON = {
  distributors: ["io.heckel.ntfy"],
  distributor: "io.heckel.ntfy",
  endpoint: "https://ntfy.sh/upX",
  p256dh: "BPk",
  auth: "c2Vj",
};
const SUBSCRIPTION = { endpoint: "https://ntfy.sh/upX", keys: { p256dh: "BPk", auth: "c2Vj" } };

it("rejects invalid permission values and tolerates only an already deleted subscription", async () => {
  expect(() => parsePhonePushStatus({ ...ON, permission: "surprise" })).toThrow("malformed");
  answers = [{ distributors: [] }];
  api.delete.mockRejectedValueOnce(new ApiError(404, "gone"));
  await disablePhonePush(parsePhonePushStatus(ON));
  api.delete.mockRejectedValueOnce(new ApiError(503, "offline"));
  await expect(disablePhonePush(parsePhonePushStatus(ON))).rejects.toThrow("offline");
  api.delete.mockRejectedValueOnce(new Error("network"));
  await expect(disablePhonePush(parsePhonePushStatus(ON))).rejects.toThrow("network");
});

let answers: unknown[] = [];
const invoke = vi.fn(async (command: string, _args?: unknown) =>
  command === "push_status" ? answers.shift() : command === "push_register" ? true : null,
);

beforeEach(() => {
  vi.clearAllMocks();
  window.__TAURI__ = { core: { invoke }, event: { listen: vi.fn() } };
});
afterEach(() => {
  delete window.__TAURI__;
});

describe("parsePhonePushStatus", () => {
  it("reads a phone with no distributor, one registered, and refuses anything else", () => {
    expect(parsePhonePushStatus({ distributors: [] })).toEqual({
      distributors: [],
      distributor: null,
      failed: null,
      subscription: null,
    });
    expect(parsePhonePushStatus(ON).subscription).toEqual(SUBSCRIPTION);
    for (const value of [null, { distributors: "ntfy" }, { distributors: [1] }]) {
      expect(() => parsePhonePushStatus(value)).toThrow(ShellError);
    }
  });
});

describe("turning push on and off on the phone", () => {
  it("registers with the deployment's key, waits for the endpoint and tells the server", async () => {
    answers = [{ distributors: ["io.heckel.ntfy"] }, { distributors: ["io.heckel.ntfy"] }, ON];
    const wait = vi.fn(async () => {});
    const status = await enablePhonePush(wait);
    expect(invoke).toHaveBeenCalledWith("push_register", { vapid: "BPub" });
    expect(wait).toHaveBeenCalledTimes(2);
    expect(status.subscription).toEqual(SUBSCRIPTION);
    expect(api.post).toHaveBeenCalledWith("/push/subscriptions", SUBSCRIPTION);
  });

  it("tells the server nothing when no endpoint came", async () => {
    answers = [{ distributors: ["io.heckel.ntfy"], failed: "NETWORK" }];
    const status = await enablePhonePush(async () => {});
    expect(status.failed).toBe("NETWORK");
    expect(api.post).not.toHaveBeenCalled();
  });

  it("forgets the endpoint on the server and with the distributor", async () => {
    answers = [{ distributors: ["io.heckel.ntfy"] }];
    const status = await disablePhonePush(parsePhonePushStatus(ON));
    expect(api.delete).toHaveBeenCalledWith("/push/subscriptions", {
      params: { endpoint: "https://ntfy.sh/upX" },
    });
    expect(invoke).toHaveBeenCalledWith("push_unregister", undefined);
    expect(status.subscription).toBeNull();
    answers = [{ distributors: [] }];
    await disablePhonePush(parsePhonePushStatus({ distributors: [] }));
    expect(api.delete).toHaveBeenCalledTimes(1);
    await syncPhonePush(parsePhonePushStatus({ distributors: [] }));
    expect(api.post).not.toHaveBeenCalled();
  });

  it("waits with real time when not told how", async () => {
    vi.useFakeTimers();
    answers = [{ distributors: ["io.heckel.ntfy"] }, ON];
    const enabling = enablePhonePush();
    await vi.advanceTimersByTimeAsync(600);
    expect((await enabling).subscription).toEqual(SUBSCRIPTION);
    vi.useRealTimers();
  });
});
