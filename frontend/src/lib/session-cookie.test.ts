import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { secureCookies } from "./session-cookie";

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
