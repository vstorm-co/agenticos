/**
 * The console language a person chose, kept on their account (#2301).
 *
 * The cookie alone held it before, so a choice made on a laptop was not the
 * phone's, and an agent asked to "switch to English" had nothing to change.
 */

import { apiClient } from "./api-client";
import type { Locale } from "./locales";

export async function saveAccountLocale(locale: Locale): Promise<Locale> {
  const saved = await apiClient.put<{ locale: Locale }>("/users/me/locale", { locale });
  return saved.locale;
}
