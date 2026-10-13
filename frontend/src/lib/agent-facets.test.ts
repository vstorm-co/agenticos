import { describe, expect, it } from "vitest";

import { agentListParams, canonicalFacet, facetParams } from "./agent-facets";

describe("canonicalFacet", () => {
  it("sorts a copy without mutating the input, so React state is never corrupted", () => {
    const source = ["z", "a", "m"];
    const sorted = canonicalFacet(source);

    expect(sorted).toEqual(["a", "m", "z"]);
    // The array the caller holds is untouched - sorting state in place wedges
    // the render and the cache key.
    expect(source).toEqual(["z", "a", "m"]);
    expect(sorted).not.toBe(source);
  });

  it("returns an empty copy for an empty selection", () => {
    expect(canonicalFacet([])).toEqual([]);
  });
});

describe("facetParams", () => {
  it("emits repeated keys as tuple pairs, which the object form cannot carry", () => {
    expect(facetParams(["a", "b"], ["x"])).toEqual([
      ["category", "a"],
      ["category", "b"],
      ["tag", "x"],
    ]);
  });

  it("is empty when neither facet has a value", () => {
    expect(facetParams([], [])).toEqual([]);
  });
});

describe("agentListParams", () => {
  it("is undefined for the plain listing, so it shares one cache entry", () => {
    expect(agentListParams(false, [], [])).toBeUndefined();
  });

  it("keeps the archived-only listing as the object form it always used", () => {
    expect(agentListParams(true, [], [])).toEqual({ include_archived: "true" });
  });

  it("sends a facet as tuple pairs", () => {
    expect(agentListParams(false, ["sales"], ["urgent"])).toEqual([
      ["category", "sales"],
      ["tag", "urgent"],
    ]);
  });

  it("folds include_archived in beside the facet pairs", () => {
    expect(agentListParams(true, ["sales"], [])).toEqual([
      ["include_archived", "true"],
      ["category", "sales"],
    ]);
  });
});
