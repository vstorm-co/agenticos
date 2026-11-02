import { readFile, writeFile } from "node:fs/promises";

import { test as base, expect, type BrowserContext, type Cookie } from "@playwright/test";

import { AUTH_STATE } from "./helpers";

type StoredState = Awaited<ReturnType<BrowserContext["storageState"]>>;

function sessionCookie(cookies: Cookie[], kind: "access_token" | "refresh_token") {
  return cookies.find(
    (cookie) => cookie.name.startsWith("agenticos_") && cookie.name.endsWith(kind),
  );
}

function sessionClaims(token: string | undefined): { sub?: unknown; sid?: unknown; act?: unknown } {
  const payload = token?.split(".")[1];
  if (!payload) return {};
  try {
    return JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
  } catch {
    return {};
  }
}

/**
 * Write the owner session's rotated cookies back to `AUTH_STATE`.
 *
 * Every spec opens a new context from that file, but the session it holds
 * rotates its refresh token once the 15-minute access cookie lapses, and the
 * backend refuses a refresh token two rotations old. Without this, every spec
 * that starts more than 15 minutes after sign-in replays a spent token and lands
 * on /login. Only the two session cookies are copied, and only when they still
 * belong to the same, unimpersonated session: a spec that signed out, signed in
 * as someone else or switched an organization in local storage leaves the file
 * as it found it.
 */
async function keepSharedSession(context: BrowserContext): Promise<void> {
  const stored = JSON.parse(await readFile(AUTH_STATE, "utf8")) as StoredState;
  const current = await context.cookies();
  const access = sessionCookie(current, "access_token");
  const refresh = sessionCookie(current, "refresh_token");
  const storedRefresh = sessionCookie(stored.cookies, "refresh_token");
  if (!access || !refresh || !storedRefresh || refresh.value === storedRefresh.value) return;
  const was = sessionClaims(sessionCookie(stored.cookies, "access_token")?.value);
  const now = sessionClaims(access.value);
  if (now.act || !now.sid || now.sid !== was.sid || now.sub !== was.sub) return;
  const renewed = new Set([access.name, refresh.name]);
  stored.cookies = [
    ...stored.cookies.filter((cookie) => !renewed.has(cookie.name)),
    access,
    refresh,
  ];
  await writeFile(AUTH_STATE, JSON.stringify(stored, null, 2));
}

/**
 * The suite's `test`, with one thing added: a page whose data layer failed
 * cannot pass.
 *
 * Every dashboard page here is a client component that fans out to several
 * queries, and every one of them renders its empty state when a query fails.
 * "No skills yet" and "the skills request returned 502" are the same pixels, so
 * a spec asserting on an empty list is a spec asserting on nothing — which is
 * how this suite came to be green against a backend that was never started.
 *
 * Most specs fix that by asserting on seeded rows. This fixture covers the rest:
 * a resource the seed legitimately leaves empty (runs, approvals) has no row to
 * assert on, and the only honest way to tell "nothing happened" from "nothing
 * loaded" is whether the request behind it succeeded.
 *
 * Only 5xx counts. A 401 from a deliberately wrong password and a 403 from a
 * refusal are the product working; those are what several specs are *for*.
 */
export const test = base.extend<{
  apiFailures: string[];
  releaseMetadata: void;
  sharedSession: void;
}>({
  sharedSession: [
    async ({ context, storageState }, use) => {
      await use();
      if (storageState === AUTH_STATE) await keepSharedSession(context);
    },
    { auto: true },
  ],
  releaseMetadata: [
    async ({ page }, use) => {
      // Public GitHub releases change independently of the seeded deployment.
      // The release-notes journey supplies its own deterministic release instead.
      await page.route("**/api/releases/current", (route) =>
        route.fulfill({ json: { release: null } }),
      );
      await page.route("**/api/releases/latest", (route) =>
        route.fulfill({ json: { latest: null } }),
      );
      await use();
    },
    { auto: true },
  ],
  apiFailures: [
    async ({ page }, use) => {
      const failures: string[] = [];

      page.on("response", (response) => {
        if (response.status() < 500) return;
        const { pathname } = new URL(response.url());
        if (!pathname.startsWith("/api/")) return;
        // RAG needs an embedding provider, which a test deployment has no key
        // for — collection stats answer 500 by design there. Nothing in this
        // suite tests RAG, and failing every page that shows a document count
        // because of it would bury the failures that mean something.
        if (pathname.startsWith("/api/rag/")) return;
        failures.push(`${response.status()} ${response.request().method()} ${pathname}`);
      });

      await use(failures);

      expect(
        failures,
        "the page made API calls that failed — whatever it rendered, it rendered without data",
      ).toEqual([]);
    },
    { auto: true },
  ],
});

export { expect } from "@playwright/test";
