import { expect, it } from "vitest";

import { UNKNOWN_REASONS, knownReason } from "./skill-check-reasons";

it("knows every reason the type names, and nothing else", () => {
  expect(UNKNOWN_REASONS).toHaveLength(11);
  expect(UNKNOWN_REASONS.every(knownReason)).toBe(true);
  expect(knownReason("evidence_only")).toBe(false);
  expect(knownReason("toString")).toBe(false);
});
