import { describe, expect, it } from "vitest";

import { fitViewOptions, minZoomFor } from "./fit-view";

describe("fitViewOptions", () => {
  it("keeps the legibility floor on a wide screen", () => {
    expect(fitViewOptions(false, false).minZoom).toBe(0.55);
    expect(fitViewOptions(true, false).minZoom).toBe(0.5);
  });

  it("lets a phone shrink the whole flow into view, editable or read-only", () => {
    expect(fitViewOptions(false, true)).toMatchObject({ padding: 0.2, minZoom: 0.15 });
    expect(fitViewOptions(true, true)).toMatchObject({ padding: 0.15, minZoom: 0.15 });
  });

  it("never lets the canvas zoom out less far than its own framing went", () => {
    expect(minZoomFor(false)).toBeLessThanOrEqual(fitViewOptions(true, false).minZoom!);
    expect(minZoomFor(true)).toBeLessThanOrEqual(fitViewOptions(false, true).minZoom!);
  });
});
