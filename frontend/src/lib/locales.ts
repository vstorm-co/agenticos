/**
 * Which locales exist, in one place both the app and the build config can read.
 *
 * `src/i18n.ts` pulls in `next-intl/server` and the whole English catalog, so
 * `next.config.ts` cannot import it to find out - which is how the moved-route
 * redirects came to hard-code `en|pl` and answer a German bookmark with a 404
 * while every other surface had been translated.
 */
export const locales = ["en", "pl", "de"] as const;

export type Locale = (typeof locales)[number];

export const defaultLocale: Locale = "en";
