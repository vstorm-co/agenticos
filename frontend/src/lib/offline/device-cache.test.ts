import { webcrypto } from "node:crypto";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores/auth-store";
import { useOfflineStore } from "@/stores/offline-store";
import type { ConversationMessagesResponse, User } from "@/types";
import {
  isNetworkFailure,
  keepConsoleCode,
  keepOutbox,
  keptFile,
  keptOutbox,
  MAX_KEPT_FILE_BYTES,
  offlineAvailable,
  readConversation,
  readThrough,
  RECENT_CONVERSATIONS,
  refreshOutboxCounts,
  wipeDeviceCache,
} from "./device-cache";

const PHONE = { platform: "android", version: "0.1.0", window: "main", vibrancy: false };

const offline = () => Promise.reject(new TypeError("Failed to fetch"));
const thread = (text: string): ConversationMessagesResponse => ({
  items: [{ id: "m-1", role: "user", content: text } as ConversationMessagesResponse["items"][0]],
  total: 1,
  cost: null,
});

function signIn(id: string) {
  useAuthStore.setState({ user: { id } as User, isAuthenticated: true });
}

/** What the copy holds for `name`, read the way a request without a network reads it. */
function keptCopy(name: "approvals") {
  return readThrough(name, offline);
}

beforeEach(() => {
  vi.stubGlobal("indexedDB", new IDBFactory());
  vi.stubGlobal("crypto", webcrypto);
  window.__AGENTICOS_SHELL__ = PHONE;
  wipeDeviceCache();
  signIn("u-1");
});

afterEach(() => {
  // First: a test may have taken `window` away.
  vi.unstubAllGlobals();
  delete window.__AGENTICOS_SHELL__;
  useAuthStore.setState({ user: null, isAuthenticated: false });
  vi.restoreAllMocks();
});

describe("offlineAvailable", () => {
  it("is on in the apps and off in a browser tab", () => {
    expect(offlineAvailable()).toBe(true);
    delete window.__AGENTICOS_SHELL__;
    expect(offlineAvailable()).toBe(false);
  });

  it("is off where the browser has no IndexedDB or no WebCrypto", () => {
    vi.stubGlobal("indexedDB", undefined);
    Reflect.deleteProperty(window, "indexedDB");
    expect(offlineAvailable()).toBe(false);
  });

  it("is off where there is no window: on the server", () => {
    vi.stubGlobal("window", undefined);
    expect(offlineAvailable()).toBe(false);
  });

  it("is on for a console installed to the home screen", () => {
    delete window.__AGENTICOS_SHELL__;
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query === "(display-mode: standalone)",
    }));
    expect(offlineAvailable()).toBe(true);
  });
});

/** An IndexedDB that refuses everything, as a browser with storage turned off does. */
function storageRefused() {
  vi.stubGlobal("indexedDB", {
    open: () => {
      throw new Error("storage refused");
    },
    deleteDatabase: () => {
      const request: { error: Error; onerror?: () => void } = {
        error: new Error("delete refused"),
      };
      setTimeout(() => request.onerror?.());
      return request;
    },
  });
}

describe("isNetworkFailure", () => {
  it("is a request that never reached a server, not a refusal or a cancel", () => {
    expect(isNetworkFailure(new TypeError("Failed to fetch"))).toBe(true);
    expect(isNetworkFailure(new Error("502"))).toBe(false);
    expect(isNetworkFailure(new DOMException("aborted", "AbortError"))).toBe(false);
  });
});

describe("readThrough", () => {
  it("answers from the server, and from the copy when the server cannot be reached", async () => {
    const answer = { items: [], total: 3 };
    expect(await readThrough("approvals", () => Promise.resolve(answer))).toEqual(answer);

    await vi.waitFor(async () => expect(await keptCopy("approvals")).toEqual(answer));
    expect(useOfflineStore.getState().savedAt).toBeInstanceOf(Date);
  });

  it("stops saying the screen is a copy once the server answers", async () => {
    useOfflineStore.getState().servedFromDevice(new Date());
    await readThrough("approvals", () => Promise.resolve({ items: [], total: 0 }));

    expect(useOfflineStore.getState().savedAt).toBeNull();
  });

  it("lets a refusal stand rather than answering it with the copy", async () => {
    await readThrough("approvals", () => Promise.resolve({ items: [], total: 1 }));
    await vi.waitFor(async () => expect(await keptCopy("approvals")).toBeTruthy());

    const refusal = new Error("403");
    await expect(readThrough("approvals", () => Promise.reject(refusal))).rejects.toBe(refusal);
  });

  it("fails as the request failed when there is no copy", async () => {
    await expect(keptCopy("approvals")).rejects.toBeInstanceOf(TypeError);
    expect(useOfflineStore.getState().savedAt).toBeNull();
  });

  it("keeps nothing in a browser tab", async () => {
    delete window.__AGENTICOS_SHELL__;
    await readThrough("approvals", () => Promise.resolve({ items: [], total: 1 }));
    window.__AGENTICOS_SHELL__ = PHONE;

    await expect(keptCopy("approvals")).rejects.toBeInstanceOf(TypeError);
  });

  it("does not keep an answer that lands after the tenant's copy was wiped", async () => {
    let answer!: (value: { items: never[]; total: number }) => void;
    const late = readThrough("approvals", () => new Promise((resolve) => (answer = resolve)));
    wipeDeviceCache();
    answer({ items: [], total: 9 });
    await late;

    await new Promise((resolve) => setTimeout(resolve, 20));
    await expect(keptCopy("approvals")).rejects.toBeInstanceOf(TypeError);
  });

  it("passes the request through with nobody signed in", async () => {
    useAuthStore.setState({ user: null });
    await expect(readThrough("approvals", offline)).rejects.toBeInstanceOf(TypeError);
    expect(await readThrough("approvals", () => Promise.resolve({ items: [], total: 1 }))).toEqual({
      items: [],
      total: 1,
    });
  });

  it("answers from the server when the copy cannot be written, and says so", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    storageRefused();
    wipeDeviceCache();

    expect(await readThrough("approvals", () => Promise.resolve({ items: [], total: 1 }))).toEqual({
      items: [],
      total: 1,
    });
    await vi.waitFor(() =>
      expect(warn).toHaveBeenCalledWith("offline", "keep approvals", expect.any(Error)),
    );
  });

  it("fails as the request failed when the copy cannot be read", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    storageRefused();
    wipeDeviceCache();

    await expect(keptCopy("approvals")).rejects.toBeInstanceOf(TypeError);
    expect(warn).toHaveBeenCalledWith("offline", "read approvals", expect.any(Error));
  });

  it("opens the next account's copy after a copy that never opened", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    storageRefused();
    await keepOutbox("c-1", [{ id: "q-1", content: "x" }]);

    vi.stubGlobal("indexedDB", new IDBFactory());
    signIn("u-2");
    await keepOutbox("c-1", [{ id: "q-2", content: "y" }]);
    expect(await keptOutbox("c-1")).toEqual([{ id: "q-2", content: "y" }]);
  });

  it("does not show one account the copy another account kept", async () => {
    await readThrough("approvals", () => Promise.resolve({ items: [], total: 1 }));
    await vi.waitFor(async () => expect(await keptCopy("approvals")).toBeTruthy());

    signIn("u-2");
    await expect(keptCopy("approvals")).rejects.toBeInstanceOf(TypeError);
  });
});

describe("readConversation", () => {
  it("keeps the most recently opened conversations and lets the oldest go", async () => {
    for (let n = 0; n <= RECENT_CONVERSATIONS; n++) {
      await readConversation(`c-${n}`, () => Promise.resolve(thread(`text ${n}`)));
      // One at a time: each keeps its copy and moves the list before the next.
      await vi.waitFor(async () =>
        expect(await readConversation(`c-${n}`, offline)).toEqual(thread(`text ${n}`)),
      );
    }

    await expect(readConversation("c-0", offline)).rejects.toBeInstanceOf(TypeError);
    expect(await readConversation("c-1", offline)).toEqual(thread("text 1"));
  });
});

describe("a recent conversation's files", () => {
  const withFiles = (...ids: string[]): ConversationMessagesResponse => ({
    items: [
      {
        id: "m-1",
        role: "user",
        content: "see attached",
        files: ids.map((id) => ({
          id,
          filename: `${id}.png`,
          mime_type: "image/png",
          file_type: "image",
        })),
      } as ConversationMessagesResponse["items"][0],
    ],
    total: 1,
    cost: null,
  });
  const file = (status = 200, size = 3) => ({
    ok: status === 200,
    status,
    blob: async () => new Blob(["x".repeat(size)], { type: "image/png" }),
  });

  it("are kept the first time the thread is read with them, and open offline", async () => {
    const fetchFile = vi.fn(async () => file());
    vi.stubGlobal("fetch", fetchFile);

    await readConversation("c-1", () => Promise.resolve(withFiles("f-1", "f-2")));
    await vi.waitFor(async () => expect(await keptFile("f-2")).not.toBeNull());
    const kept = (await keptFile("f-1"))!;
    expect(kept.type).toBe("image/png");
    expect(await kept.text()).toBe("xxx");
    expect(fetchFile).toHaveBeenCalledWith("/api/files/f-1", { credentials: "include" });

    fetchFile.mockClear();
    await readConversation("c-1", () => Promise.resolve(withFiles("f-1", "f-2")));
    // Long enough for the background keeping to have run, had it fetched anything.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(fetchFile).not.toHaveBeenCalled();
  });

  it("leaves one too large, or one that will not load, to the network", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("big")
          ? file(200, MAX_KEPT_FILE_BYTES + 1)
          : url.endsWith("gone")
            ? file(404)
            : file(),
      ),
    );

    await readConversation("c-1", () => Promise.resolve(withFiles("big", "gone", "ok")));
    await vi.waitFor(async () => expect(await keptFile("ok")).not.toBeNull());
    expect(await keptFile("big")).toBeNull();
    expect(await keptFile("gone")).toBeNull();
  });

  it("go with their conversation when it is no longer a recent one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => file()),
    );
    await readConversation("c-0", () => Promise.resolve(withFiles("f-0")));
    await vi.waitFor(async () => expect(await keptFile("f-0")).not.toBeNull());
    for (let n = 1; n <= RECENT_CONVERSATIONS; n++) {
      await readConversation(`c-${n}`, () => Promise.resolve(thread(`text ${n}`)));
      await vi.waitFor(async () => expect(await readConversation(`c-${n}`, offline)).toBeTruthy());
    }

    expect(await keptFile("f-0")).toBeNull();
  });

  it("are not kept for a tenant left while they were loading", async () => {
    let answer!: (value: ReturnType<typeof file>) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise((resolve) => (answer = resolve))),
    );
    await readConversation("c-1", () => Promise.resolve(withFiles("f-1")));
    await vi.waitFor(() => expect(answer).toBeDefined());
    wipeDeviceCache();
    answer(file());

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(await keptFile("f-1")).toBeNull();
  });

  it("are nothing in a browser tab, and nothing when the copy cannot be read", async () => {
    delete window.__AGENTICOS_SHELL__;
    expect(await keptFile("f-1")).toBeNull();

    window.__AGENTICOS_SHELL__ = PHONE;
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    storageRefused();
    wipeDeviceCache();
    expect(await keptFile("f-1")).toBeNull();
    expect(warn).toHaveBeenCalledWith("offline", "read file", expect.any(Error));
  });
});

describe("the outbox", () => {
  it("keeps a conversation's messages, counts every outbox, and forgets an emptied one", async () => {
    await keepOutbox("c-1", [{ id: "q-1", content: "first" }]);
    await keepOutbox(null, [
      { id: "q-2", content: "a new chat" },
      { id: "q-3", content: "and more" },
    ]);

    expect(await keptOutbox("c-1")).toEqual([{ id: "q-1", content: "first" }]);
    expect(useOfflineStore.getState().outbox).toEqual(
      expect.arrayContaining([
        { conversationId: "c-1", count: 1 },
        { conversationId: null, count: 2 },
      ]),
    );

    await keepOutbox("c-1", []);
    expect(await keptOutbox("c-1")).toEqual([]);
    useOfflineStore.getState().setOutbox([]);
    await refreshOutboxCounts();
    expect(useOfflineStore.getState().outbox).toEqual([{ conversationId: null, count: 2 }]);
  });

  it("keeps nothing for a tenant wiped while the write was on its way", async () => {
    const write = keepOutbox("c-1", [{ id: "q-1", content: "first" }]);
    wipeDeviceCache();
    await write;

    expect(await keptOutbox("c-1")).toEqual([]);
  });

  it("is read for nobody once somebody else has signed in", async () => {
    await keepOutbox("c-1", [{ id: "q-1", content: "first" }]);
    useOfflineStore.getState().setOutbox([]);

    const read = keptOutbox("c-1");
    const counted = refreshOutboxCounts();
    signIn("u-2");

    expect(await read).toEqual([]);
    await counted;
    expect(useOfflineStore.getState().outbox).toEqual([]);
  });

  it("is wiped with the rest of the tenant's copy", async () => {
    await keepOutbox("c-1", [{ id: "q-1", content: "first" }]);
    wipeDeviceCache();

    expect(useOfflineStore.getState().outbox).toEqual([]);
    expect(await keptOutbox("c-1")).toEqual([]);
  });

  it("is nothing in a browser tab", async () => {
    delete window.__AGENTICOS_SHELL__;
    await keepOutbox("c-1", [{ id: "q-1", content: "first" }]);
    expect(await keptOutbox("c-1")).toEqual([]);
    await refreshOutboxCounts();
    expect(useOfflineStore.getState().outbox).toEqual([]);
  });

  it("says where it failed rather than failing the chat", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    storageRefused();
    wipeDeviceCache();

    await keepOutbox("c-1", [{ id: "q-1", content: "first" }]);
    expect(await keptOutbox("c-1")).toEqual([]);
    await refreshOutboxCounts();
    expect(warn).toHaveBeenCalledWith("offline", "keep outbox", expect.any(Error));
  });
});

describe("keepConsoleCode", () => {
  it("installs the console's service worker in the apps", async () => {
    const register = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, serviceWorker: { register } });

    await keepConsoleCode();

    expect(register).toHaveBeenCalledWith("/sw.js");
  });

  it("installs nothing in a browser tab, or where there are no service workers", async () => {
    const register = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, serviceWorker: { register } });
    delete window.__AGENTICOS_SHELL__;
    await keepConsoleCode();
    expect(register).not.toHaveBeenCalled();

    window.__AGENTICOS_SHELL__ = PHONE;
    vi.stubGlobal("navigator", {});
    await expect(keepConsoleCode()).resolves.toBeUndefined();
  });

  it("says where a web view refused it", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const refusal = new Error("not an app-bound domain");
    vi.stubGlobal("navigator", { serviceWorker: { register: () => Promise.reject(refusal) } });

    await keepConsoleCode();

    expect(warn).toHaveBeenCalledWith("offline", "register worker", refusal);
  });
});

describe("wipeDeviceCache", () => {
  it("has nothing to delete in a browser tab", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    delete window.__AGENTICOS_SHELL__;
    storageRefused();
    wipeDeviceCache();

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(warn).not.toHaveBeenCalled();
  });

  it("says where the browser refused to delete the copy", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    storageRefused();
    wipeDeviceCache();

    await vi.waitFor(() => expect(warn).toHaveBeenCalledWith("offline", "wipe", expect.any(Error)));
  });
});
