import { test as base, expect } from "@playwright/test";

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
export const test = base.extend<{ apiFailures: string[] }>({
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
