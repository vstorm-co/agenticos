import { apiClient } from "./api-client";
import type { StoredEntry } from "./dashboard/preference";

export const CHAT_HOME_ITEMS = ["inbox", "starters", "greeting", "feature_hints"] as const;
export type ChatHomeItem = (typeof CHAT_HOME_ITEMS)[number];
export type ChatHomeOptions = Record<ChatHomeItem, boolean>;
export type ChatHomeOverrides = Partial<Record<ChatHomeItem, boolean | null>>;
export type ReminderDays = 1 | 3 | 7;
export interface OnboardingReminderOverrides {
  enabled?: boolean | null;
  snooze_days?: ReminderDays | null;
}
export interface OnboardingReminderOptions {
  enabled: boolean;
  snooze_days: ReminderDays;
}
export interface OnboardingReminderRead {
  availability: boolean;
  organization_defaults: OnboardingReminderOverrides;
  preferences: OnboardingReminderOverrides;
  effective: OnboardingReminderOptions;
}
export type ChatCostVisibility = "everyone" | "spend_privileged" | "nobody";
export interface ChatCostPolicy {
  availability: boolean;
  organization_policy: ChatCostVisibility;
  preference: boolean | null;
  permitted: boolean;
  effective: boolean;
}
export interface ConsoleNotices {
  desktop_install_prompt?: boolean | null;
  product_notices?: boolean | null;
}
export interface CatalogPolicy {
  mode: "all" | "allow-list" | "available";
  keys: string[];
}
export interface ConsoleCatalogPreferences {
  mcp_gallery?: CatalogPolicy | null;
  skill_gallery?: CatalogPolicy | null;
}
export interface ConsolePreferences extends ConsoleNotices, ConsoleCatalogPreferences {
  navigation?: string[] | null;
}
export interface ConsoleRoleDefaults extends ConsoleCatalogPreferences {
  dashboard?: { entries: StoredEntry[] } | null;
  navigation?: string[] | null;
}
export interface ConsolePresentation {
  dashboard_default?: { entries: StoredEntry[] } | null;
  organization_mcp_gallery?: CatalogPolicy;
  organization_skill_gallery?: CatalogPolicy;
  available_mcp_gallery?: CatalogPolicy;
  available_skill_gallery?: CatalogPolicy;
  simple_navigation: string[];
  navigation_available: string[];
  organization_navigation: string[];
  navigation: string[];
  preferences: ConsolePreferences;
  notices_available: ConsoleNotices;
  organization_notices: ConsoleNotices;
  desktop_install_prompt: boolean;
  product_notices: boolean;
}
export interface ConsoleExperienceChanges {
  console?: ConsolePreferences | null;
  chat_costs?: boolean | null;
  preferences?: ChatHomeOverrides | null;
  reminders?: OnboardingReminderOverrides | null;
}
export interface ConsoleExperience {
  presentation?: ConsolePresentation;
  costs?: ChatCostPolicy;
  reminders: OnboardingReminderRead;
  availability: ChatHomeOptions;
  organization_defaults: ChatHomeOverrides;
  preferences: ChatHomeOverrides;
  effective: ChatHomeOptions;
}
export const DEFAULT_CHAT_HOME: ChatHomeOptions = {
  inbox: true,
  starters: true,
  greeting: true,
  feature_hints: true,
};

/** Pin the owner even if a queued request outlives a workspace switch. */
export function readConsoleExperience(organizationId: string): Promise<ConsoleExperience> {
  return apiClient.get<ConsoleExperience>("/users/me/console-experience", {
    headers: { "X-Organization-Id": organizationId },
  });
}
export function saveConsoleExperience(
  organizationId: string,
  changes: ConsoleExperienceChanges,
): Promise<ConsoleExperience> {
  return apiClient.patch<ConsoleExperience>("/users/me/console-experience", changes, {
    headers: { "X-Organization-Id": organizationId },
  });
}
