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

  it("leaves the brand to the title template", () => {
    // The root layout declares `%s | <brand>` and Next applies it to whatever a
    // page returns, so appending the brand here as well is how every title read
    // `Sign in | agenticos | Acme AI` - the template's half current, this half
    // frozen at build time.
    expect(pageMetadata({ title: "Terms", description: "…" }).title).toBe("Terms");
  });

  it("opts out of the template when the page's title is the brand", () => {
    // `absolute` is how Next is told to skip it. Without that the home page reads
    // "agenticos | agenticos".
    expect(pageMetadata({ title: SITE.name, description: "…" }).title).toEqual({
      absolute: SITE.name,
    });
  });

  it("carries the brand into the titles no template touches", () => {
    // OpenGraph and Twitter titles are not templated, so a shared link would
    // otherwise unfurl as a bare page name with no product on it.
    const meta = pageMetadata({ title: "Terms", description: "…" });

    expect(meta.openGraph?.title).toBe(`Terms | ${SITE.name}`);
    expect(meta.twitter?.title).toBe(`Terms | ${SITE.name}`);
  });

  it("uses the deployment's own name when the caller has read it", () => {
    // Every `generateMetadata` in the app passes it, so a renamed deployment is
    // not still `agenticos` on a shared link.
    const meta = pageMetadata({ title: "Terms", description: "…", brand: "Acme AI" });

    expect(meta.title).toBe("Terms");
    expect(meta.openGraph?.title).toBe("Terms | Acme AI");
    expect(meta.openGraph?.siteName).toBe("Acme AI");
    expect(meta.openGraph?.images).toEqual([
      expect.objectContaining({ alt: expect.stringContaining("Acme AI") }),
    ]);
  });

  it("opts out of the template when the title is the deployment's own name", () => {
    expect(pageMetadata({ title: "Acme AI", description: "…", brand: "Acme AI" }).title).toEqual({
      absolute: "Acme AI",
    });
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
