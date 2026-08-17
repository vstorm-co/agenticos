import { afterEach, describe, expect, it, vi } from "vitest";

import { clientId } from "./ids";

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
