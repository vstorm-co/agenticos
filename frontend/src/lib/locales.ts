/**
 * Which locales exist, in one place both the app and the build config can read.
 *
 * `src/i18n.ts` pulls in `next-intl/server` and the whole English catalog, so
 * `next.config.ts` cannot import it to find out - which is how the moved-route
 * redirects came to hard-code `en|pl` and answer a German bookmark with a 404
 * while every other surface had been translated.
 *
 * The T3 fork ships English only. Upstream's Polish, German and Turkish
 * catalogs are deleted after every upstream sync (see `T3_FORK.md`).
 */
export const locales = ["en"] as const;

export type Locale = (typeof locales)[number];

export const defaultLocale: Locale = "en";

/**
 * Locales upstream served and this fork does not. A bookmark or shared link
 * under one of these prefixes redirects to the same page in English.
 */
export const retiredLocales = ["pl", "de", "tr"] as const;

/** Whether a person can choose a language at all. Every language control hides when not. */
export const hasLocaleChoice: boolean = (locales as readonly string[]).length > 1;
