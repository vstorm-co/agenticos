import { NextRequest, type NextResponse } from "next/server";
import { describe, expect, it } from "vitest";

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

describe("the locale a visitor picked", () => {
  it("still holds on a path that carries no prefix", () => {
    // The whole of #285: `router.push("/orgs")` and any plain `<Link>` drop the
    // prefix, and with it - before this - the language.
    expect(redirectedTo(middleware(request("/orgs", { locale: "pl" })))).toBe("/pl/orgs");
  });

  it("still holds at the root", () => {
    expect(redirectedTo(middleware(request("/", { locale: "pl" })))).toBe("/pl");
  });

  it("keeps the query string it was carrying", () => {
    expect(redirectedTo(middleware(request("/orgs?create=1", { locale: "pl" })))).toBe(
      "/pl/orgs?create=1",
    );
  });

  it("does not redirect a path that already names it", () => {
    expect(redirectedTo(middleware(request("/pl/orgs", { locale: "pl" })))).toBeNull();
  });

  it("does not prefix a path whose prefix is merely in the wrong case", () => {
    // next-intl matches a prefix case-insensitively and canonicalises `/PL/orgs`
    // to `/pl/orgs`. Reading it as unprefixed here made that `/pl/PL/orgs` - a 404
    // on a URL that worked before the cookie existed.
    expect(redirectedTo(middleware(request("/PL/orgs", { locale: "pl" })))).toBe("/pl/orgs");
  });

  it("loses to the path when the two disagree, so a shared URL means what it says", () => {
    expect(redirectedTo(middleware(request("/pl/orgs", { locale: "en" })))).toBeNull();
    expect(redirectedTo(middleware(request("/orgs", { locale: "en" })))).toBeNull();
  });
});

describe("a visitor who picked nothing", () => {
  it("is served the default locale, unprefixed", () => {
    expect(redirectedTo(middleware(request("/orgs")))).toBeNull();
  });

  it("is served English even from a Polish browser", () => {
    // `localeDetection: false` is deliberate - Polish is opted into, never sniffed.
    // Reading the cookie by hand is what must not quietly reintroduce the header.
    expect(
      redirectedTo(middleware(request("/orgs", { acceptLanguage: "pl-PL,pl;q=0.9" }))),
    ).toBeNull();
  });

  it("is unaffected by a cookie naming a locale this deployment does not have", () => {
    expect(redirectedTo(middleware(request("/orgs", { locale: "de" })))).toBeNull();
    expect(redirectedTo(middleware(request("/orgs", { locale: "" })))).toBeNull();
  });
});

describe("a path that names a locale", () => {
  it("is remembered, so the next unprefixed link keeps it", () => {
    // next-intl writes the cookie itself only when `accept-language` disagrees with
    // the locale it resolved, so a Polish browser opening a shared `/pl/...` link
    // persisted nothing and reverted to English on the next plain `<Link>`.
    const response = middleware(request("/pl/orgs", { acceptLanguage: "pl-PL,pl;q=0.9" }));
    expect(cookieSetTo(response)).toBe("pl");
  });

  it("is remembered for a browser that asked for nothing in particular", () => {
    expect(cookieSetTo(middleware(request("/pl/orgs")))).toBe("pl");
  });

  it("says nothing when the cookie already agrees", () => {
    expect(cookieSetTo(middleware(request("/pl/orgs", { locale: "pl" })))).toBeNull();
  });

  it("leaves a background request alone", () => {
    // The router revalidates routes of the locale just switched away from; writing
    // the cookie from one of those would undo the switch that has just been made.
    expect(cookieSetTo(middleware(request("/pl/orgs", { dest: "empty" })))).toBeNull();
  });
});
