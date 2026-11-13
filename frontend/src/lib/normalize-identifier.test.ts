import { describe, expect, it } from "vitest";
import { normalizeIdentifier } from "./normalize-identifier";

describe("normalizeIdentifier", () => {
  it.each([
    ["Strategic-Diagnostic", "strategic-diagnostic"],
    ["  Strategic   Diagnostic  ", "strategic-diagnostic"],
    ["Refund_Policy / Summary!", "refund-policy-summary"],
    ["Zażółć GĘŚLĄ jaźń", "zazolc-gesla-jazn"],
    ["Café Déjà Vu", "cafe-deja-vu"],
    ["Cafe\u0301", "cafe"],
    ["／Daily Review", "daily-review"],
    ["a--b", "a-b"],
    ["---", ""],
    ["🤖", ""],
    ["", ""],
    ["123", "123"],
  ])("formats %j without inventing a name", (value, expected) => {
    expect(normalizeIdentifier(value)).toBe(expected);
    expect(normalizeIdentifier(expected)).toBe(expected);
  });

  it("does not silently shorten names into a different or colliding identifier", () => {
    expect(normalizeIdentifier("A".repeat(65))).toBe("a".repeat(65));
  });
});
