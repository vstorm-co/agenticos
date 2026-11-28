import { afterEach, describe, expect, it, vi } from "vitest";

import { clientId, clientUuid } from "./ids";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("clientId", () => {
  it("mints a distinct id on every call", () => {
    const ids = new Set(Array.from({ length: 100 }, clientId));
    expect(ids.size).toBe(100);
  });

  it("uses the platform generator where the context is secure", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "11111111-2222-3333-4444-555555555555" });
    expect(clientId()).toBe("11111111-2222-3333-4444-555555555555");
  });

  it("still mints an id where the context is not secure", () => {
    // Plain HTTP on anything but `localhost` has no `crypto.randomUUID`, which
    // is exactly where an embedded widget on an internal host runs. Reaching
    // for it unguarded would take chat down with a TypeError.
    vi.stubGlobal("crypto", undefined);
    expect(clientId()).toMatch(/^id-\d+-[a-z0-9]+$/);
    expect(clientId()).not.toBe(clientId());
  });

  it("still mints an id where crypto exists without randomUUID", () => {
    vi.stubGlobal("crypto", { getRandomValues: () => new Uint8Array() });
    expect(clientId()).toMatch(/^id-\d+-[a-z0-9]+$/);
  });
});

describe("clientUuid", () => {
  it("uses the native UUID generator when available", () => {
    const randomUUID = vi.fn(() => "11111111-2222-4333-8444-555555555555");
    vi.stubGlobal("crypto", { randomUUID });
    expect(clientUuid()).toBe("11111111-2222-4333-8444-555555555555");
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  it("keeps UUIDv4 format without randomUUID", () => {
    vi.stubGlobal("crypto", { getRandomValues: crypto.getRandomValues.bind(crypto) });
    const ids = new Set(Array.from({ length: 20 }, clientUuid));
    expect(ids.size).toBe(20);
    for (const id of ids) {
      expect(id).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
    }
  });
});
