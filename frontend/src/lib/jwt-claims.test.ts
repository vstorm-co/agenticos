import { describe, expect, it } from "vitest";

import { isImpersonation, unverifiedClaims } from "./jwt-claims";

function token(claims: Record<string, unknown>): string {
  const body = Buffer.from(JSON.stringify(claims)).toString("base64url");
  return `eyJhbGciOiJIUzI1NiJ9.${body}.signature-not-checked`;
}

/**
 * Reading a cookie's claims without a key.
 *
 * The one question asked of it is whether the browser holds an impersonation -
 * a token with `act` - so the refresh route can refuse to swap it for the
 * administrator's own token behind a request the page thinks it made as
 * somebody else (#1044). Everything here is about not throwing on garbage: the
 * cookie is whatever the browser sent.
 */
describe("unverifiedClaims", () => {
  it("reads the payload segment", () => {
    expect(unverifiedClaims(token({ sub: "u-1", act: "a-1" }))).toEqual({
      sub: "u-1",
      act: "a-1",
    });
  });

  it("answers nothing for something that is not a token", () => {
    expect(unverifiedClaims("not-a-token")).toBeNull();
    expect(unverifiedClaims("")).toBeNull();
  });

  it("answers nothing for a payload that is not JSON, or not an object", () => {
    expect(unverifiedClaims("a.!!!.c")).toBeNull();
    expect(unverifiedClaims(`a.${Buffer.from("[1]").toString("base64url")}.c`)).toBeNull();
    expect(unverifiedClaims(`a.${Buffer.from("null").toString("base64url")}.c`)).toBeNull();
  });
});

describe("isImpersonation", () => {
  it("is true only for a token naming an actor behind its subject", () => {
    expect(isImpersonation(token({ sub: "u-1", act: "a-1", sid: "s-1" }))).toBe(true);
    expect(isImpersonation(token({ sub: "u-1" }))).toBe(false);
    expect(isImpersonation(token({ sub: "u-1", act: "" }))).toBe(false);
    expect(isImpersonation("garbage")).toBe(false);
  });
});
