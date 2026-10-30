import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  get: vi.fn(async () => ({ public_key: "BPk-Kd3_d0Ag" })),
  post: vi.fn(async () => ({ sent: 1, gone: 0, failed: 0 })),
  delete: vi.fn(async () => undefined),
}));
vi.mock("@/lib/api-client", () => ({ apiClient: api }));

import { disablePush, enablePush, pushState, sendTestPush } from "./web-push";

function install({
  permission = "default",
  asked = "granted",
  existing = null as null | { endpoint: string; unsubscribe: () => Promise<boolean> },
} = {}) {
  const created = {
    toJSON: () => ({ endpoint: "https://fcm.googleapis.com/x", keys: { p256dh: "a", auth: "b" } }),
  };
  const pushManager = {
    getSubscription: vi.fn(async () => existing),
    subscribe: vi.fn(async (_options: PushSubscriptionOptionsInit) => created),
  };
  const registration = { pushManager };
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: {
      getRegistration: vi.fn(async () => (existing ? registration : undefined)),
      register: vi.fn(async () => registration),
      ready: Promise.resolve(registration),
    },
  });
  vi.stubGlobal("PushManager", function PushManager() {});
  vi.stubGlobal(
    "Notification",
    Object.assign(function Notification() {}, {
      permission,
      requestPermission: vi.fn(async () => asked),
    }),
  );
  return pushManager;
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "serviceWorker");
});

describe("pushState", () => {
  it("names a browser with no push at all, a blocked one, and whether it is on", async () => {
    expect(await pushState()).toBe("unsupported");
    install({ permission: "denied" });
    expect(await pushState()).toBe("blocked");
    install();
    expect(await pushState()).toBe("off");
    install({ existing: { endpoint: "e", unsubscribe: async () => true } });
    expect(await pushState()).toBe("on");
  });
});

describe("enablePush", () => {
  it("subscribes with the deployment's key and tells the server", async () => {
    const pushManager = install();
    expect(await enablePush()).toBe("on");
    const options = pushManager.subscribe.mock.calls[0]?.[0];
    expect(options?.applicationServerKey).toBeInstanceOf(Uint8Array);
    expect(api.post).toHaveBeenCalledWith("/push/subscriptions", {
      endpoint: "https://fcm.googleapis.com/x",
      keys: { p256dh: "a", auth: "b" },
    });
  });

  it("stops where the person said no, or did not answer", async () => {
    expect(await enablePush()).toBe("unsupported");
    install({ asked: "denied" });
    expect(await enablePush()).toBe("blocked");
    install({ asked: "default" });
    expect(await enablePush()).toBe("off");
    expect(api.post).not.toHaveBeenCalled();
  });
});

describe("disablePush and the test", () => {
  it("unsubscribes here and on the server, and is off when nothing was on", async () => {
    const unsubscribe = vi.fn(async () => true);
    install({ existing: { endpoint: "https://fcm.googleapis.com/x", unsubscribe } });
    expect(await disablePush()).toBe("off");
    expect(api.delete).toHaveBeenCalledWith("/push/subscriptions", {
      params: { endpoint: "https://fcm.googleapis.com/x" },
    });
    expect(unsubscribe).toHaveBeenCalled();
    install();
    expect(await disablePush()).toBe("off");
    expect(await sendTestPush()).toEqual({ sent: 1, gone: 0, failed: 0 });
  });
});
