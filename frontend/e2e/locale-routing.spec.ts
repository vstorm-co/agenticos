import { expect, test } from "./fixtures";

test.describe("locale routing over HTTP", () => {
  for (const path of ["/login", "/dashboard", "/chat"]) {
    test(`serves the English document at ${path} without a redirect loop`, async ({ request }) => {
      const response = await request.get(path, {
        headers: { Cookie: "NEXT_LOCALE=en" },
        maxRedirects: 3,
      });

      expect(response.status()).toBe(200);
      expect(response.headers()["content-type"]).toContain("text/html");
      expect(new URL(response.url()).pathname).toBe(path);
    });
  }

  test("serves a client navigation as RSC rather than redirecting back to itself", async ({
    request,
  }) => {
    const response = await request.get("/chat", {
      headers: { Cookie: "NEXT_LOCALE=en", RSC: "1" },
      maxRedirects: 3,
    });

    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("text/x-component");
  });

  test("restores Polish on an unprefixed navigation", async ({ request }) => {
    const response = await request.get("/chat", {
      headers: { Cookie: "NEXT_LOCALE=pl" },
      maxRedirects: 3,
    });

    expect(response.status()).toBe(200);
    expect(new URL(response.url()).pathname).toBe("/pl/chat");
  });
});
