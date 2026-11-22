import { apiClient } from "./api-client";

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
export interface ConsoleExperienceChanges {
  preferences?: ChatHomeOverrides | null;
  reminders?: OnboardingReminderOverrides | null;
}
export interface ConsoleExperience {
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
