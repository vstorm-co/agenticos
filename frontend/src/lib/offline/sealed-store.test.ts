import { webcrypto } from "node:crypto";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SealedStore, wipeSealedStore, type DeviceApis } from "./sealed-store";

interface Records {
  note: { text: string };
  [list: `list:${string}`]: string[];
}

let apis: DeviceApis;

/** What IndexedDB holds under `name`, as stored - before any decryption. */
async function raw(name: string): Promise<unknown> {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = apis.indexedDB.open("agenticos-offline", 1);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  const value = await new Promise((resolve) => {
    const request = db.transaction("sealed").objectStore("sealed").get(name);
    request.onsuccess = () => resolve(request.result);
  });
  db.close();
  return value;
}

beforeEach(() => {
  apis = { indexedDB: new IDBFactory(), subtle: webcrypto.subtle as SubtleCrypto };
});

afterEach(() => {
  vi.useRealTimers();
});

describe("SealedStore", () => {
  it("gives back what was put, and stores none of it in the clear", async () => {
    const store = await SealedStore.open<Records>("u-1", apis);
    await store.put("note", { text: "the quarterly numbers" });

    expect((await store.get("note"))?.value).toEqual({ text: "the quarterly numbers" });
    const stored = await raw("note");
    expect(JSON.stringify(stored)).not.toContain("quarterly");
    expect(new TextDecoder().decode((stored as { data: ArrayBuffer }).data)).not.toContain(
      "quarterly",
    );
    store.close();
  });

  it("keeps a key nobody can export", async () => {
    const store = await SealedStore.open<Records>("u-1", apis);
    await store.put("note", { text: "x" });
    store.close();
    const db = await new Promise<IDBDatabase>((resolve) => {
      const request = apis.indexedDB.open("agenticos-offline", 1);
      request.onsuccess = () => resolve(request.result);
    });
    const seal = await new Promise<{ key: CryptoKey }>((resolve) => {
      const request = db.transaction("meta").objectStore("meta").get("seal");
      request.onsuccess = () => resolve(request.result);
    });
    db.close();

    expect(seal.key.extractable).toBe(false);
    await expect(apis.subtle.exportKey("raw", seal.key)).rejects.toThrow();
  });

  it("reopens for the same person with what they kept", async () => {
    const first = await SealedStore.open<Records>("u-1", apis);
    await first.put("list:a", ["one"]);
    first.close();

    const again = await SealedStore.open<Records>("u-1", apis);
    expect((await again.get("list:a"))?.value).toEqual(["one"]);
    again.close();
  });

  it("deletes what somebody else kept before opening for the next person", async () => {
    const first = await SealedStore.open<Records>("u-1", apis);
    await first.put("note", { text: "mine" });
    first.close();

    const next = await SealedStore.open<Records>("u-2", apis);
    expect(await next.get("note")).toBeNull();
    next.close();
  });

  it("drops a copy older than asked for", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-01T10:00:00Z"));
    const store = await SealedStore.open<Records>("u-1", apis);
    await store.put("note", { text: "old" });
    vi.setSystemTime(new Date("2026-10-09T10:00:00Z"));

    expect(await store.get("note", 7 * 24 * 60 * 60 * 1000)).toBeNull();
    expect(await store.get("note")).toBeNull();
    store.close();
  });

  it("says when a copy was saved", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-01T10:00:00Z"));
    const store = await SealedStore.open<Records>("u-1", apis);
    await store.put("note", { text: "x" });

    expect((await store.get("note"))?.savedAt).toEqual(new Date("2026-10-01T10:00:00Z"));
    store.close();
  });

  it("names records by prefix, and forgets a deleted one", async () => {
    const store = await SealedStore.open<Records>("u-1", apis);
    await store.put("list:a", []);
    await store.put("list:b", []);
    await store.put("note", { text: "x" });
    await store.delete("list:b");

    expect(await store.names("list:")).toEqual(["list:a"]);
    store.close();
  });

  it("is gone, key and all, after a wipe", async () => {
    const store = await SealedStore.open<Records>("u-1", apis);
    await store.put("note", { text: "x" });
    store.close();
    await wipeSealedStore(apis);

    const reopened = await SealedStore.open<Records>("u-1", apis);
    expect(await reopened.get("note")).toBeNull();
    reopened.close();
  });

  it("lets go of the database when another tab deletes it", async () => {
    const store = await SealedStore.open<Records>("u-1", apis);
    await store.put("note", { text: "x" });
    await wipeSealedStore(apis);

    const reopened = await SealedStore.open<Records>("u-1", apis);
    expect(await reopened.get("note")).toBeNull();
    reopened.close();
  });

  it("refuses a database it does not know, rather than reading it", async () => {
    // A newer console's schema, by version: opening it as version 1 fails.
    await new Promise<void>((resolve) => {
      const request = apis.indexedDB.open("agenticos-offline", 2);
      request.onsuccess = () => {
        request.result.close();
        resolve();
      };
    });

    await expect(SealedStore.open<Records>("u-1", apis)).rejects.toBeTruthy();
  });

  it("finishes a wipe that another connection holds up, once it lets go", async () => {
    const holder = await new Promise<IDBDatabase>((resolve) => {
      const request = apis.indexedDB.open("agenticos-offline", 1);
      request.onupgradeneeded = () => {
        request.result.createObjectStore("meta");
        request.result.createObjectStore("sealed");
      };
      request.onsuccess = () => resolve(request.result);
    });

    await wipeSealedStore(apis);
    holder.close();

    const reopened = await SealedStore.open<Records>("u-1", apis);
    expect(await reopened.get("note")).toBeNull();
    reopened.close();
  });

  it("reports a wipe the browser refused", async () => {
    const refusal = new Error("refused");
    const indexedDB = {
      deleteDatabase: () => {
        const request: { error: Error; onerror?: () => void } = { error: refusal };
        setTimeout(() => request.onerror?.());
        return request;
      },
    } as unknown as IDBFactory;

    await expect(wipeSealedStore({ indexedDB, subtle: apis.subtle })).rejects.toBe(refusal);
  });
});
