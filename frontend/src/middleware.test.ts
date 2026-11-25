import { NextRequest, type NextResponse } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import middleware from "@/middleware";
import { LOCALE_COOKIE_NAME } from "@/lib/locale-routing";

function request(
  path: string,
  init?: { locale?: string; acceptLanguage?: string; dest?: string },
): NextRequest {
  const headers = new Headers({ "sec-fetch-dest": init?.dest ?? "document" });
  if (init?.acceptLanguage) headers.set("accept-language", init.acceptLanguage);
  if (init?.locale) headers.set("cookie", `${LOCALE_COOKIE_NAME}=${init.locale}`);
  return new NextRequest(new URL(path, "https://agenticos.test"), { headers });
}

/** Where a response sends the browser next, or `null` when it sends it nowhere. */
function redirectedTo(response: Response): string | null {
  const location = response.headers.get("location");
  return location ? new URL(location).pathname + new URL(location).search : null;
}

/** The locale a response asks the browser to remember, or `null` when it asks nothing. */
function cookieSetTo(response: NextResponse): string | null {
  return response.cookies.get(LOCALE_COOKIE_NAME)?.value ?? null;
}

describe("an English-only deployment", () => {
  it("ignores a cookie left by a locale it no longer serves", () => {
    // A visitor who picked Polish before the fork went English-only still holds
    // `NEXT_LOCALE=pl`. Restoring it would send every plain `<Link>` to `/pl/...`.
    expect(redirectedTo(middleware(request("/orgs", { locale: "pl" })))).toBeNull();
    expect(redirectedTo(middleware(request("/", { locale: "de" })))).toBeNull();
  });

  it("serves English to a Polish browser, unprefixed", () => {
    expect(
      redirectedTo(middleware(request("/orgs", { acceptLanguage: "pl-PL,pl;q=0.9" }))),
    ).toBeNull();
  });

  it("is unaffected by a cookie naming a locale it never had", () => {
    expect(redirectedTo(middleware(request("/orgs", { locale: "fr" })))).toBeNull();
    expect(redirectedTo(middleware(request("/orgs", { locale: "" })))).toBeNull();
  });

  it("is unaffected by a cookie naming a locale this deployment does not have", () => {
    expect(redirectedTo(middleware(request("/orgs", { locale: "es" })))).toBeNull();
    expect(redirectedTo(middleware(request("/orgs", { locale: "" })))).toBeNull();
  });
});

describe("a path under a retired locale", () => {
  it.each([
    ["/pl/orgs", "/orgs"],
    ["/de/agents/abc", "/agents/abc"],
    ["/tr/login", "/login"],
    ["/pl", "/"],
    ["/de/", "/"],
  ])("sends %s to its English page %s", (from, to) => {
    const response = middleware(request(from));
    expect(response.status).toBe(308);
    expect(redirectedTo(response)).toBe(to);
  });

  it("keeps the query string", () => {
    expect(redirectedTo(middleware(request("/pl/orgs?create=1")))).toBe("/orgs?create=1");
  });

  it("matches the prefix whatever case it was written in", () => {
    expect(redirectedTo(middleware(request("/PL/orgs")))).toBe("/orgs");
  });

  it("wins over a cookie naming the same retired locale, and writes none", () => {
    const response = middleware(request("/pl/orgs", { locale: "pl" }));
    expect(redirectedTo(response)).toBe("/orgs");
    expect(cookieSetTo(response)).toBeNull();
  });

  it("leaves a route whose first segment merely starts with one alone", () => {
    expect(redirectedTo(middleware(request("/plans")))).toBeNull();
    expect(redirectedTo(middleware(request("/design")))).toBeNull();
  });
});

describe("the content security policy", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("is stamped on every page response, naming the deployment's public origins", () => {
    // `next.config.ts` runs at build and could only name `localhost`; the API and
    // socket origins are read from the environment per request (#1544), so the
    // middleware is the one place the header can say what the deployment is.
    vi.stubEnv("PUBLIC_API_URL", "https://api.acme.example");
    vi.stubEnv("PUBLIC_WS_URL", "wss://ws.acme.example");

    const policy = middleware(request("/orgs")).headers.get("content-security-policy");

    expect(policy).toContain("connect-src 'self' https://api.acme.example wss://ws.acme.example");
    expect(policy).toContain("frame-ancestors 'none'");
  });

  it("rides the locale redirect too, so no document leaves without it", () => {
    const redirected = middleware(request("/pl/orgs"));

    expect(redirected.headers.get("location")).toContain("/orgs");
    expect(redirected.headers.get("content-security-policy")).toContain("default-src 'self'");
  });

  it("carries a fresh script nonce and never 'unsafe-inline'", () => {
    // Next stamps this nonce onto its inline scripts; a constant one would be
    // `'unsafe-inline'` an attacker can read and reuse, so it is per request (#1624).
    const first = middleware(request("/orgs")).headers.get("content-security-policy") ?? "";
    const second = middleware(request("/orgs")).headers.get("content-security-policy") ?? "";

    const scriptSrc = /script-src ([^;]*)/.exec(first)?.[1] ?? "";
    expect(scriptSrc).toContain("'nonce-");
    expect(scriptSrc).toContain("'strict-dynamic'");
    expect(scriptSrc).not.toContain("'unsafe-inline'");

    const nonceOf = (policy: string) => /'nonce-([^']+)'/.exec(policy)?.[1];
    expect(nonceOf(first)).toBeTruthy();
    expect(nonceOf(first)).not.toBe(nonceOf(second));
  });
});
