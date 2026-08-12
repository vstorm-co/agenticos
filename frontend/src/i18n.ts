import { getRequestConfig } from "next-intl/server";

import en from "../messages/en.json";

export const locales = ["en", "pl"] as const;
export type Locale = (typeof locales)[number];

export const defaultLocale: Locale = "en";

type Messages = { [key: string]: string | Messages };

/**
 * One locale's catalog, with English underneath it.
 *
 * English is the source language: every string in the product is written there
 * first, and a translation arrives later or not at all. Without a fallback that gap
 * is a hard failure - `next-intl` renders the key itself and reports an error for a
 * message the locale is missing - so shipping a feature in English would break the
 * Polish UI until somebody translated it, which is exactly the wrong incentive.
 *
 * Merged rather than duplicated. `pl.json` holds the strings that have actually been
 * translated and nothing else, so there is no second copy of nine hundred English
 * sentences to keep in step - and `frontend/scripts/check-i18n.ts` only has to hold
 * one catalog complete.
 */
function withEnglishUnderneath(messages: Messages): Messages {
  const merge = (base: Messages, over: Messages): Messages => {
    const merged: Messages = { ...base };
    for (const [key, value] of Object.entries(over)) {
      const beneath = merged[key];
      if (typeof value === "object" && typeof beneath === "object") {
        merged[key] = merge(beneath, value);
      } else {
        merged[key] = value;
      }
    }
    return merged;
  };
  return merge(en as Messages, messages);
}

export default getRequestConfig(async ({ requestLocale }) => {
  let locale = await requestLocale;

  if (!locale || !locales.includes(locale as Locale)) {
    locale = defaultLocale;
  }

  const messages = (await import(`../messages/${locale}.json`)).default as Messages;
  return { locale, messages: withEnglishUnderneath(messages) };
});

export function getLocaleLabel(locale: Locale): string {
  const labels: Record<Locale, string> = {
    en: "English",
    pl: "Polski",
  };
  return labels[locale];
}

export function getLocaleFlag(locale: Locale): string {
  const flags: Record<Locale, string> = {
    en: "🇬🇧",
    pl: "🇵🇱",
  };
  return flags[locale];
}
