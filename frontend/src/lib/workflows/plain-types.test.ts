import { describe, expect, it } from "vitest";

import { plainType } from "./plain-types";

describe("plainType", () => {
  it.each([
    ["string", "text"],
    ["string:email", "text"],
    ["string:date-time", "date"],
    ["string:date", "date"],
    ["string:uuid", "id"],
    ["integer", "number"],
    ["number", "number"],
    ["boolean", "yesNo"],
    ["array", "list"],
    ["array:set", "list"],
    ["object", "object"],
    ["Payload", "object"],
    ["null", "empty"],
    ["unknown", "any"],
    ["union(string:uuid|null)", "id"],
    ["union(object|null)", "object"],
    ["union(integer|number)", "number"],
    ["union(string|integer)", "any"],
  ])("reads %s as %s", (token, kind) => {
    expect(plainType(token)).toBe(kind);
  });
});
