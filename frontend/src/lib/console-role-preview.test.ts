import { describe, expect, it } from "vitest";
import { previewCatalogPolicies } from "./console-role-preview";

describe("role catalog preview", () => {
  it("keeps deployment and role allow-lists intersected", () => {
    expect(
      previewCatalogPolicies([
        { mode: "allow-list", keys: ["a", "b"] },
        { mode: "allow-list", keys: ["b", "c"] },
      ]),
    ).toEqual({ approvedLimit: 1, availableOnly: false });
  });
  it("keeps an empty allow-list intentionally empty", () => {
    expect(previewCatalogPolicies([{ mode: "allow-list", keys: [] }])).toEqual({
      approvedLimit: 0,
      availableOnly: false,
    });
  });
  it("reports an upper bound when connected availability is unknown", () => {
    expect(
      previewCatalogPolicies([
        { mode: "allow-list", keys: ["a", "b"] },
        { mode: "available", keys: [] },
      ]),
    ).toEqual({ approvedLimit: 2, availableOnly: true });
  });
  it("does not claim a count for unrestricted or inherited catalogs", () => {
    expect(previewCatalogPolicies([null, undefined, { mode: "all", keys: [] }])).toEqual({
      approvedLimit: null,
      availableOnly: false,
    });
  });
});
