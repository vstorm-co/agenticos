import { describe, expect, it } from "vitest";

import { specText } from "./version-history";

describe("specText", () => {
  it("serializes the same spec identically regardless of key order", () => {
    // A version fetched from the API and a draft assembled in the Builder can
    // carry their keys in different orders; a diff between them must be empty.
    const a = { name: "x", instructions: "hi", skills: [{ b: 1, a: 2 }] };
    const b = { skills: [{ a: 2, b: 1 }], instructions: "hi", name: "x" };

    expect(specText(a)).toBe(specText(b));
  });

  it("renders a multi-line instruction as its lines, not as one escaped string", () => {
    // The whole point of diffing YAML: editing one paragraph of instructions
    // must show as that paragraph, which needs each line to be its own line.
    const text = specText({ instructions: "You are a support agent.\n\nBe brief." });

    expect(text).toContain("You are a support agent.\n");
    expect(text).toContain("Be brief.");
    expect(text).not.toContain("\\n");
  });
});
