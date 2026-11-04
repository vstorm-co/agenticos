import type { Node } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { makeDefinition } from "@/components/workflows/validation/fixtures";

import { minimapColour } from "./minimap-colour";

const step = (category: string | null): Node => ({
  id: "n",
  position: { x: 0, y: 0 },
  data: { definition: category === null ? null : makeDefinition({ id: "x", category }) },
});

describe("minimapColour", () => {
  it("is the family's mark, by the step's category", () => {
    expect(minimapColour(step("triggers"))).toBe("var(--family-map-start)");
    expect(minimapColour(step("agent"))).toBe("var(--family-map-ai)");
    expect(minimapColour(step("tables"))).toBe("var(--family-map-data)");
    expect(minimapColour(step("slack"))).toBe("var(--family-map-apps)");
    expect(minimapColour(step("error"))).toBe("var(--family-map-error)");
  });

  it("is Flow's grey for a step the catalog does not know, and for a note", () => {
    expect(minimapColour(step("logic"))).toBe("var(--family-map-flow)");
    expect(minimapColour(step(null))).toBe("var(--family-map-flow)");
    expect(minimapColour({ ...step("agent"), type: "note" })).toBe("var(--family-map-flow)");
  });
});
