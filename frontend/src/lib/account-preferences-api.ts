import { apiClient } from "./api-client";
import type { Look } from "./appearance";
import type { Locale } from "./locales";
import type { Theme } from "@/stores/theme-store";

export interface AccountPreferences {
  theme: Theme | null;
  look: Look | null;
  locale: Locale | null;
}

export type AppearanceChange = Partial<Pick<AccountPreferences, "theme" | "look">>;

export function readAccountPreferences(): Promise<AccountPreferences> {
  return apiClient.get<AccountPreferences>("/users/me/preferences");
}

export function saveAccountAppearance(changes: AppearanceChange): Promise<AccountPreferences> {
  return apiClient.patch<AccountPreferences>("/users/me/preferences", changes);
}
