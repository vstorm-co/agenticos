import { describe, expect, it } from "vitest";

import {
  NODE_ID_SUFFIX_LENGTH,
  bindingFieldPath,
  nodeDisplayName,
  parseBindingFieldPath,
  shortNodeId,
} from "./types";

describe("bindingFieldPath / parseBindingFieldPath", () => {
  it("joins segments JSON-Pointer style, stringifying indices", () => {
    expect(bindingFieldPath(["mappings", 0, "value"])).toBe("mappings/0/value");
    expect(bindingFieldPath(["field"])).toBe("field");
    expect(bindingFieldPath([])).toBe("");
  });

  it("escapes slash and tilde inside a segment (RFC 6901)", () => {
    expect(bindingFieldPath(["a/b", "c~d"])).toBe("a~1b/c~0d");
  });

  it("round-trips a path back to its segments", () => {
    expect(parseBindingFieldPath("mappings/0/value")).toEqual(["mappings", "0", "value"]);
    expect(parseBindingFieldPath("field")).toEqual(["field"]);
    expect(parseBindingFieldPath("")).toEqual([]);
  });

  it("decodes escapes in RFC 6901 order (~1 before ~0)", () => {
    expect(parseBindingFieldPath("a~1b/c~0d")).toEqual(["a/b", "c~d"]);
    // ~01 decodes to ~1, not to a slash: ~0 first would corrupt it.
    expect(parseBindingFieldPath("x~01y")).toEqual(["x~1y"]);
  });
});

describe("shortNodeId / nodeDisplayName", () => {
  it("takes the head of a node id", () => {
    expect(shortNodeId("abcdef123456789")).toHaveLength(NODE_ID_SUFFIX_LENGTH);
    expect(shortNodeId("abcdef123456789")).toBe("abcdef");
  });

  it("shows the bare definition name by default", () => {
    expect(nodeDisplayName("Echo", "abcdef123456789")).toBe("Echo");
  });

  it("appends a short id suffix when disambiguation is asked for", () => {
    expect(nodeDisplayName("Echo", "abcdef123456789", true)).toBe("Echo · abcdef");
  });
});
