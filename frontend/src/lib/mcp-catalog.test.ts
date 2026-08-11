import { describe, expect, it } from "vitest";

import { logoDataUri } from "./mcp-catalog";

describe("logoDataUri", () => {
  it("answers with the baked-in logo, so no page tells a third party what it is showing", () => {
    expect(logoDataUri("github.com")).toMatch(/^data:/);
  });

  it("falls back to the favicon service for a domain nobody generated", () => {
    // Reaching this in the app means `bun run gen:mcp-logos` needs a re-run; it
    // is a stale-build signal rather than a state to design for.
    expect(logoDataUri("not-in-the-map.example")).toBe(
      "https://www.google.com/s2/favicons?sz=128&domain=not-in-the-map.example",
    );
  });
});
