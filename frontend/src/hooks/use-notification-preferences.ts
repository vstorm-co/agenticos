"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/api-error";
import {
  listNotificationPreferences,
  updateNotificationPreference,
  type NotificationChannel,
  type NotificationPreference,
} from "@/lib/notification-preferences-api";

interface UseNotificationPreferencesResult {
  preferences: NotificationPreference[];
  isLoading: boolean;
  error: string | null;
  /** Whether `event_type`'s `channel` is on - unset pairs default to on
   * (the server's own default), matching what `GET` never has to say. */
  isEnabled: (eventType: string, channel: NotificationChannel) => boolean;
  setPreference: (
    eventType: string,
    channel: NotificationChannel,
    enabled: boolean,
  ) => Promise<void>;
}

/**
 * The per-user notification channel preferences (#1598, Decision 4).
 *
 * React Query owns the list, the same shape `useSlashCommands` uses: fetched
 * once, cached, and a mutation replaces its own row in the cache directly
 * rather than refetching the whole list for one flipped switch.
 */
export function useNotificationPreferences(): UseNotificationPreferencesResult {
  const tErrors = useTranslations("errors");
  const tSettings = useTranslations("pages.settings");
  const queryClient = useQueryClient();

  const {
    data: preferences = [],
    isLoading,
    error: queryError,
  } = useQuery({
    queryKey: qk.notifications.preferences(),
    queryFn: listNotificationPreferences,
  });

  const error = queryError
    ? getErrorMessage(queryError, tErrors, tSettings("failedLoadPreferences"))
    : null;

  const isEnabled = useCallback(
    (eventType: string, channel: NotificationChannel) => {
      const stored = preferences.find((p) => p.event_type === eventType && p.channel === channel);
      return stored?.enabled ?? true;
    },
    [preferences],
  );

  const setPreference = useCallback<UseNotificationPreferencesResult["setPreference"]>(
    async (eventType, channel, enabled) => {
      const updated = await updateNotificationPreference({
        event_type: eventType,
        channel,
        enabled,
      });
      queryClient.setQueryData<NotificationPreference[]>(
        qk.notifications.preferences(),
        (prev = []) => {
          const existing = prev.findIndex(
            (p) => p.event_type === eventType && p.channel === channel,
          );
          if (existing >= 0) {
            const next = prev.slice();
            next[existing] = updated;
            return next;
          }
          return [...prev, updated];
        },
      );
    },
    [queryClient],
  );

  return { preferences, isLoading, error, isEnabled, setPreference };
}
