import { defineRouting } from "next-intl/routing";

import { locales, defaultLocale, type Locale } from "@/i18n";

/**
 * The cookie holding the locale the visitor picked.
 *
 * `NEXT_LOCALE` is next-intl's own default name, written client-side by the
 * navigation APIs below, and read back - and written, for a path that names a
 * locale - by `src/middleware.ts`. It is named here rather than left to the
 * default so that every write and the read are the same constant: a divergence
 * between them is invisible - the switch appears to work,
 * because the URL prefix carries the locale for exactly as long as the current
 * page lasts.
 */
export const LOCALE_COOKIE_NAME = "NEXT_LOCALE";

/** A year. The choice is a preference, not a session. */
export const LOCALE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

/**
 * One routing configuration, shared by the middleware and the navigation APIs.
 *
 * `localePrefix: "as-needed"` - English, the default, has no prefix; Polish lives
 * under `/pl/...`.
 *
 * `localeDetection: false` because it gates the `accept-language` header as well
 * as the cookie, and a visitor with a Polish browser must still be served English
 * at the root until they ask for Polish. The cookie half is therefore kept by hand
 * in `src/middleware.ts`; see the notes there.
 */
export const routing = defineRouting({
  locales,
  defaultLocale,
  localePrefix: "as-needed",
  localeDetection: false,
  localeCookie: { name: LOCALE_COOKIE_NAME, maxAge: LOCALE_COOKIE_MAX_AGE },
});

/**
 * The locale a path names in its first segment, or `null` when it names none.
 *
 * Matched case-insensitively, because next-intl's own prefix matching is:
 * `/PL/agents` is a Polish path to it, redirected to the canonical `/pl/agents`.
 * Reading it as unprefixed here would put a second prefix on the front of a path
 * that already has one - `/pl/PL/agents`, which no route serves.
 */
export function localePrefixOf(pathname: string): Locale | null {
  const segment = pathname.split("/")[1]?.toLowerCase();
  return segment && (locales as readonly string[]).includes(segment) ? (segment as Locale) : null;
}

/** The locale the visitor picked, when this deployment serves it and it is not the default. */
export function pickedLocale(value: string | undefined): Locale | null {
  return value && value !== defaultLocale && (locales as readonly string[]).includes(value)
    ? (value as Locale)
    : null;
}
