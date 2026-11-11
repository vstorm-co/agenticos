import { describe, expect, it } from "vitest";

import { canonicalJson, sameJson } from "./canonical-json";

describe("JSON content comparison", () => {
  it("ignores nested object key order but preserves values and array order", () => {
    expect(
      sameJson(
        { config: { z: 1, a: [{ name: "Ada", id: 7 }] } },
        { config: { a: [{ id: 7, name: "Ada" }], z: 1 } },
      ),
    ).toBe(true);
    expect(sameJson([1, 2], [2, 1])).toBe(false);
    expect(sameJson({ value: 1 }, { value: "1" })).toBe(false);
    expect(sameJson({ value: null }, {})).toBe(false);
  });
  it("uses JSON wire rules for absent fields and keeps prototype-named keys", () => {
    expect(sameJson({ a: undefined, b: true }, { b: true })).toBe(true);
    expect(canonicalJson(JSON.parse('{"z":2,"__proto__":{"a":1}}'))).toBe(
      '{"__proto__":{"a":1},"z":2}',
    );
    expect(canonicalJson(undefined)).toBe("undefined");
  });
});
