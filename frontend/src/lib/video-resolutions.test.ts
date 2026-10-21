import { describe, expect, it } from "vitest";

import { resolutionLines, resolutionsAbove } from "./video-resolutions";

describe("resolutionLines", () => {
  it("reads both of the catalog's spellings as lines", () => {
    expect(resolutionLines("480p")).toBe(480);
    expect(resolutionLines(" 1080P ")).toBe(1080);
    expect(resolutionLines("4k")).toBe(2160);
  });

  it("reads a name of neither shape as 0", () => {
    expect(resolutionLines("HD")).toBe(0);
  });
});

describe("resolutionsAbove", () => {
  it("offers only what is taller than the usual resolution, shortest first", () => {
    expect(resolutionsAbove(["720p", "360p", "4k", "1080p"], "720p")).toEqual(["1080p", "4k"]);
    expect(resolutionsAbove(["720p", "480p"], "720p")).toEqual([]);
  });
});
