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

/**
 * The platform's own tool, by the exact name a run gives it: its server is
 * always attached as `agenticos` (`PLATFORM_MCP_NAME`). Matched whole, because
 * any other MCP server's `set_my_language` arrives as `<its prefix>_set_my_language`
 * and its answer is that server's word, not a write to this account.
 */
const SET_MY_LANGUAGE = "agenticos_set_my_language";

/** Record `locale` as the signed-in account's choice, in this tab. */
export function adoptAccountLocale(locale: Locale): void {
  const { user, setUser } = useAuthStore.getState();
  if (user && user.locale !== locale) setUser({ ...user, locale });
}

/**
 * The locale an agent's tool call just chose, or null when it chose none.
 *
 * The result is the API's answer, `{"locale": "en"}`; anything else is a
 * refusal the model reads, and changes nothing here.
 */
export function localeChosenBy(toolName: string, result: string): Locale | null {
  if (toolName !== SET_MY_LANGUAGE) return null;
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
