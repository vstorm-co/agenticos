import { afterEach, describe, expect, it, vi } from "vitest";

import { rememberDataset, rememberedDataset } from "./use-dataset-target";

describe("the remembered dataset", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("is remembered per person", () => {
    rememberDataset("u1", "d1");
    expect(rememberedDataset("u1")).toBe("d1");
    expect(rememberedDataset("u2")).toBeNull();
    expect(rememberedDataset(null)).toBeNull();
  });

  it("is simply forgotten where the browser keeps no storage", () => {
    const blocked = () => {
      throw new Error("blocked");
    };
    vi.stubGlobal("localStorage", { getItem: blocked, setItem: blocked });
    expect(() => rememberDataset("u1", "d1")).not.toThrow();
    expect(rememberedDataset("u1")).toBeNull();
  });
});
