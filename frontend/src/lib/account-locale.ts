/**
 * Which console language the account chose, and the two ways it changes.
 *
 * The console follows `user.locale` wherever it is open (`AccountLocale`), so the
 * store is the one place a choice is recorded: the language menu writes it as
 * the person picks, and an agent's `set_my_language` call writes it the moment
 * its result arrives in the chat - the page then switches without a reload,
 * which is the whole of "switch to English" working (#2301).
 */

import { useAuthStore } from "@/stores";

import { locales, type Locale } from "./locales";

const SET_MY_LANGUAGE = /(^|_)set_my_language$/;

/** Record `locale` as the signed-in account's choice, in this tab. */
export function adoptAccountLocale(locale: Locale): void {
  const { user, setUser } = useAuthStore.getState();
  if (user && user.locale !== locale) setUser({ ...user, locale });
}

/**
 * The locale an agent's tool call just chose, or null when it chose none.
 *
 * Matched on the tool's own name under any server prefix, so the platform's
 * server reached as `agenticos` - or from another deployment's agent - is read
 * the same. The result is the API's answer, `{"locale": "en"}`; anything else
 * is a refusal the model reads, and changes nothing here.
 */
export function localeChosenBy(toolName: string, result: string): Locale | null {
  if (!SET_MY_LANGUAGE.test(toolName)) return null;
  try {
    const parsed: unknown = JSON.parse(result);
    const locale =
      parsed && typeof parsed === "object" && "locale" in parsed ? parsed.locale : null;
    return typeof locale === "string" && (locales as readonly string[]).includes(locale)
      ? (locale as Locale)
      : null;
  } catch {
    return null;
  }
}
