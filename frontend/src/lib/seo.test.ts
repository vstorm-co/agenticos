import { afterEach, describe, expect, it, vi } from "vitest";

import { OG_LOCALE, SITE, pageMetadata } from "./seo";

/**
 * The metadata every public page is built from.
 *
 * All of it is one thing: the canonical URL and its alternates. Getting them
 * wrong is the kind of error that is invisible on the page and visible in a
 * search index months later - a canonical that points at a path that 404s, or
 * two locales claiming the same URL.
 */
describe("pageMetadata", () => {
  it("puts the locale in the canonical URL, because every public page has one", () => {
    const meta = pageMetadata({ title: "Terms", description: "…", path: "/legal/terms" });

    expect(meta.alternates?.canonical).toBe(`${SITE.url}/en/legal/terms`);
  });

  it("names the same page in every locale the deployment serves", () => {
    // Without the alternates each translation competes with the other as a
    // duplicate.
    const meta = pageMetadata({ title: "Terms", description: "…", path: "/legal/terms" });

    expect(meta.alternates?.languages).toEqual({
      en: `${SITE.url}/en/legal/terms`,
      pl: `${SITE.url}/pl/legal/terms`,
    });
  });

  it("canonicalises the home page as the locale root, not as a trailing slash", () => {
    const meta = pageMetadata({ title: SITE.name, description: "…" });

    expect(meta.alternates?.canonical).toBe(`${SITE.url}/en`);
    expect(meta.alternates?.languages).toEqual({
      en: `${SITE.url}/en`,
      pl: `${SITE.url}/pl`,
    });
  });

  it("does not repeat the brand when the page is the brand", () => {
    // "AgenticOS | AgenticOS" is what a title template does to a home page.
    expect(pageMetadata({ title: SITE.name, description: "…" }).title).toBe(SITE.name);
  });

  it("adds the brand to every other title", () => {
    expect(pageMetadata({ title: "Terms", description: "…" }).title).toBe(`Terms | ${SITE.name}`);
  });

  it("takes a path with no leading slash and one with a trailing slash the same way", () => {
    // Both are what a caller writes by hand, and either would otherwise produce
    // a canonical nobody can reach.
    expect(
      pageMetadata({ title: "T", description: "…", path: "legal" }).alternates?.canonical,
    ).toBe(`${SITE.url}/en/legal`);
    expect(
      pageMetadata({ title: "T", description: "…", path: "/legal/" }).alternates?.canonical,
    ).toBe(`${SITE.url}/en/legal`);
  });

  it("says which locale a page is in, and which others exist", () => {
    const meta = pageMetadata({ title: "Regulamin", description: "…", locale: "pl" });

    expect(meta.openGraph?.locale).toBe(OG_LOCALE.pl);
    expect(meta.openGraph?.alternateLocale).toEqual([OG_LOCALE.en]);
  });

  it("falls back to the dynamic OG image, and takes an override", () => {
    expect(pageMetadata({ title: "T", description: "…" }).twitter?.images).toEqual([
      `${SITE.url}/opengraph-image`,
    ]);
    expect(
      pageMetadata({ title: "T", description: "…", ogImage: "https://cdn.example/x.png" }).twitter
        ?.images,
    ).toEqual(["https://cdn.example/x.png"]);
  });

  it("asks to be indexed, and asks not to be when told", () => {
    expect(pageMetadata({ title: "T", description: "…" }).robots).toMatchObject({ index: true });
    expect(pageMetadata({ title: "T", description: "…", noindex: true }).robots).toEqual({
      index: false,
      follow: false,
    });
  });

  it("leaves the Twitter handle out rather than emitting an empty one", () => {
    // `twitter:site` with no value is worse than no tag: it is a broken link to
    // an account that does not exist.
    const meta = pageMetadata({ title: "T", description: "…" });

    expect(SITE.twitter).toBe("");
    expect(meta.twitter).not.toHaveProperty("site");
  });
});

describe("the canonical origin", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("comes from the deployment, with any trailing slash removed", async () => {
    // A trailing slash here produces `https://site.com//en` in every canonical
    // the site emits.
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", "https://agenticos.example/");
    vi.resetModules();

    const { SITE: fresh } = await import("./seo");

    expect(fresh.url).toBe("https://agenticos.example");
  });

  it("falls back to localhost so a dev build has absolute URLs at all", async () => {
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", undefined);
    vi.resetModules();

    const { SITE: fresh } = await import("./seo");

    expect(fresh.url).toBe("http://localhost:3000");
  });
});
