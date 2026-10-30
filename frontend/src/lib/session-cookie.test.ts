import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { sessionCookieName, secureCookies } from "./session-cookie";

describe("secureCookies", () => {
  it("is off over plain http, where WebKit would discard a Secure cookie", () => {
    expect(secureCookies(new NextRequest("http://localhost:3000/api/auth/login"))).toBe(false);
  });

  it("is on over https", () => {
    expect(secureCookies(new NextRequest("https://agenticos.acme.com/api/auth/login"))).toBe(true);
  });

  it("trusts the proxy's first forwarded scheme over the hop it arrived on", () => {
    const behindTls = new NextRequest("http://frontend:3000/api/auth/login", {
      headers: { "x-forwarded-proto": "https, http" },
    });
    expect(secureCookies(behindTls)).toBe(true);
    const behindPlain = new NextRequest("https://frontend:3000/api/auth/login", {
      headers: { "x-forwarded-proto": "http" },
    });
    expect(secureCookies(behindPlain)).toBe(false);
  });
});

describe("local instance sessions", () => {
  it("keeps default cookies compatible and distinguishes two instances on localhost", () => {
    expect(sessionCookieName("access_token")).toBe("agenticos_access_token");
    expect(sessionCookieName("access_token", "one")).not.toBe(
      sessionCookieName("access_token", "two"),
    );
    expect(sessionCookieName("refresh_token", "one")).not.toBe(
      sessionCookieName("access_token", "one"),
    );
  });
  it("rejects invalid cookie names", () => {
    expect(() => sessionCookieName("access_token", "bad; name")).toThrow();
  });
});
