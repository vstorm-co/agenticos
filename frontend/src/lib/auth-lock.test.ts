import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { markRefreshed, refreshedRecently, withAuthLock } from "./auth-lock";

beforeEach(() => localStorage.clear());

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("withAuthLock", () => {
  it("runs the work under the one named lock every tab shares", async () => {
    const request = vi.fn((_name: string, fn: () => Promise<string>) => fn());
    vi.stubGlobal("navigator", { ...navigator, locks: { request } });

    await expect(withAuthLock(() => Promise.resolve("done"))).resolves.toBe("done");
    expect(request).toHaveBeenCalledWith("agenticos-auth-refresh", expect.any(Function));
  });

  it("runs the work unserialized where the browser has no Web Locks", async () => {
    // Plain HTTP is not a secure context, and `navigator.locks` is absent there.
    vi.stubGlobal("navigator", { userAgent: "test" });

    await expect(withAuthLock(() => Promise.resolve("done"))).resolves.toBe("done");
  });

  it("runs the work outside a browser, where there is no navigator at all", async () => {
    vi.stubGlobal("navigator", undefined);

    await expect(withAuthLock(() => Promise.resolve("done"))).resolves.toBe("done");
  });
});

describe("the recent-refresh marker", () => {
  it("is recent right after a refresh, and not before one", () => {
    expect(refreshedRecently()).toBe(false);

    markRefreshed();

    expect(refreshedRecently()).toBe(true);
  });

  it("goes stale after a few seconds", () => {
    vi.useFakeTimers();
    markRefreshed();

    vi.advanceTimersByTime(10_001);

    expect(refreshedRecently()).toBe(false);
  });

  it("does not count a refresh stamped ahead of the clock", () => {
    // A clock set back, or another tab's clock ahead: read as recent, every 401
    // until time caught up would retry the expired cookies instead of refreshing.
    localStorage.setItem("agenticos:auth-refreshed-at", String(Date.now() + 60_000));

    expect(refreshedRecently()).toBe(false);
  });

  it("ignores a value that is not a time", () => {
    localStorage.setItem("agenticos:auth-refreshed-at", "garbage");

    expect(refreshedRecently()).toBe(false);
  });

  it("does without storage when the browser blocks it", () => {
    const blocked = () => {
      throw new Error("blocked");
    };
    vi.stubGlobal("localStorage", { getItem: blocked, setItem: blocked });

    expect(() => markRefreshed()).not.toThrow();
    expect(refreshedRecently()).toBe(false);
  });
});
