"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface DesktopNotificationPreferences {
  completed: boolean;
  failed: boolean;
  approvals: boolean;
  questions: boolean;
  other: boolean;
  hide_previews: boolean;
  muted_conversations: string[];
}
export const DEFAULT_DESKTOP_NOTIFICATIONS: DesktopNotificationPreferences = {
  completed: true,
  failed: true,
  approvals: true,
  questions: true,
  other: true,
  hide_previews: true,
  muted_conversations: [],
};
interface DesktopPreferencesState {
  notifications: Record<string, DesktopNotificationPreferences>;
  reviewed: Record<string, string>;
  setNotifications: (scope: string, value: DesktopNotificationPreferences) => void;
  review: (scope: string, revision: string) => void;
}
export const useDesktopPreferencesStore = create<DesktopPreferencesState>()(
  persist(
    (set) => ({
      notifications: {},
      reviewed: {},
      setNotifications: (scope, value) =>
        set((state) => ({ notifications: { ...state.notifications, [scope]: value } })),
      review: (scope, revision) =>
        set((state) => ({ reviewed: { ...state.reviewed, [scope]: revision } })),
    }),
    { name: "desktop-preferences", version: 1 },
  ),
);

/** Browser storage is already per server origin; isolate accounts and organizations within it. */
export function desktopScope(
  userId: string | null | undefined,
  organizationId: string | null,
): string | null {
  return userId && organizationId ? JSON.stringify([userId, organizationId]) : null;
}
