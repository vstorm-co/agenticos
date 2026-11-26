"use client";

import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { adoptAccountLocale } from "@/lib/account-locale";
import { getErrorMessage } from "@/lib/api-error";
import {
  readAccountPreferences,
  saveAccountAppearance,
  type AccountPreferences,
  type AppearanceChange,
} from "@/lib/account-preferences-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores";
import { useThemeStore } from "@/stores/theme-store";

/** Share deliberate appearance choices, retaining browser/desktop defaults until chosen. */
export function useAccountAppearance(): void {
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const client = useQueryClient();
  const tErrors = useTranslations("errors");
  const key = qk.accountPreferences(userId);
  const lastLanguage = useRef({
    owner: userId,
    locale: useAuthStore.getState().user?.locale ?? null,
  });
  useEffect(() => {
    if (lastLanguage.current.owner !== userId) {
      lastLanguage.current = {
        owner: userId,
        locale: useAuthStore.getState().user?.locale ?? null,
      };
    }
  }, [userId]);
  const query = useQuery({
    queryKey: key,
    queryFn: readAccountPreferences,
    enabled: userId !== null,
    refetchInterval: 10000,
  });
  const mutation = useMutation({
    // Rapid choices must reach the server in the order the person made them.
    scope: { id: `account-appearance-${userId}` },
    mutationFn: ({ owner, changes }: { owner: string; changes: AppearanceChange }) => {
      if (useAuthStore.getState().user?.id !== owner) throw new Error(tErrors("sessionExpired"));
      return saveAccountAppearance(changes);
    },
    onMutate: async ({ owner, changes }) => {
      const ownedKey = qk.accountPreferences(owner);
      await client.cancelQueries({ queryKey: ownedKey });
      client.setQueryData<AccountPreferences>(ownedKey, (previous) => ({
        theme: null,
        look: null,
        locale: null,
        ...previous,
        ...changes,
      }));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
    onSettled: (_data, _error, { owner }) =>
      client.invalidateQueries({ queryKey: qk.accountPreferences(owner) }),
  });
  const save = useRef(mutation.mutate);
  useEffect(() => {
    save.current = mutation.mutate;
  }, [mutation.mutate]);

  useEffect(() => {
    if (!userId) return;
    return useThemeStore.subscribe((next, previous) => {
      if (next.editRevision === previous.editRevision || next.editedField === null) return;
      // Choosing the rendered default also sets an account override. Repeating
      // a choice retries an unsaved value, including before a failed read recovers.
      const changes: AppearanceChange =
        next.editedField === "theme" ? { theme: next.theme } : { look: next.look };
      save.current({ owner: userId, changes });
    });
  }, [userId]);

  useEffect(() => {
    if (!userId || !query.data || mutation.isPending) return;
    const { theme, look, locale } = query.data;
    // Only a new server choice can override the current page: an unchanged
    // snapshot must not undo a language the person is still saving locally.
    if (locale !== lastLanguage.current.locale) {
      lastLanguage.current.locale = locale;
      if (locale !== null) adoptAccountLocale(locale);
    }
    // Remote adoption never invokes the edit setters, so it cannot echo a write.
    useThemeStore.setState({
      ...(theme === null ? {} : { theme }),
      ...(look === null ? {} : { look }),
    });
  }, [userId, query.data, mutation.isPending]);
}
