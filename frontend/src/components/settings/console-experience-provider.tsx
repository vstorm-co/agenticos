"use client";

import { createContext, useContext, useEffect, useRef, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { qk } from "@/lib/query-keys";
import type { StoredEntry } from "@/lib/dashboard/preference";
import { useConsoleExperience } from "@/hooks/use-console-experience";
import {
  DEFAULT_CHAT_HOME,
  type OnboardingReminderOptions,
  type ChatHomeOptions,
} from "@/lib/console-experience-api";

const HIDDEN_CHAT_HOME: ChatHomeOptions = {
  inbox: false,
  starters: false,
  greeting: false,
  feature_hints: false,
};

const DEFAULT_REMINDERS: OnboardingReminderOptions = { enabled: true, snooze_days: 1 };
export const OnboardingReminderContext =
  createContext<OnboardingReminderOptions>(DEFAULT_REMINDERS);

interface ConsolePresentationView {
  dashboardDefault: StoredEntry[] | null;
  pending: boolean;
  navigation: readonly string[] | null;
  desktopInstallPrompt: boolean;
  productNotices: boolean;
}
export type ConsolePresentationOptions = ConsolePresentationView &
  ({ problem: false; retry?: never } | { problem: true; retry: () => void });
const DEFAULT_PRESENTATION: ConsolePresentationOptions = {
  dashboardDefault: null,
  pending: false,
  navigation: null,
  desktopInstallPrompt: true,
  productNotices: true,
  problem: false,
};
const PENDING_PRESENTATION: ConsolePresentationOptions = {
  ...DEFAULT_PRESENTATION,
  pending: true,
  navigation: [],
  desktopInstallPrompt: false,
  productNotices: false,
};
export const ConsolePresentationContext =
  createContext<ConsolePresentationOptions>(DEFAULT_PRESENTATION);

export const ChatCostContext = createContext(true);

export const ChatHomeContext = createContext<ChatHomeOptions>(DEFAULT_CHAT_HOME);

/** Authenticated console only: public chat and embedded builders keep their own contracts. */
export function ConsoleExperienceProvider({ children }: { children: ReactNode }) {
  const { data, error, refetch, organizationId, userId } = useConsoleExperience();
  const client = useQueryClient();
  const lastCatalog = useRef<string | null>(null);
  const catalogVersion = JSON.stringify([
    organizationId,
    userId,
    data?.presentation?.available_mcp_gallery,
    data?.presentation?.available_skill_gallery,
    data?.presentation?.organization_mcp_gallery,
    data?.presentation?.organization_skill_gallery,
    data?.presentation?.preferences.mcp_gallery,
    data?.presentation?.preferences.skill_gallery,
  ]);
  useEffect(() => {
    if (!data || error) return;
    const previous = lastCatalog.current;
    lastCatalog.current = catalogVersion;
    if (previous === null || previous === catalogVersion) return;
    void Promise.all([
      client.invalidateQueries({ queryKey: qk.mcpServers.catalog() }),
      client.invalidateQueries({ queryKey: qk.mcpServers.lists() }),
      client.invalidateQueries({ queryKey: qk.mcpServers.entries() }),
      client.invalidateQueries({ queryKey: qk.skills.gallery() }),
    ]);
  }, [catalogVersion, client, data, error]);
  const reminders =
    !error && data ? data.reminders.effective : { enabled: false, snooze_days: 1 as const };
  const policy: ConsolePresentationView =
    !data || error
      ? PENDING_PRESENTATION
      : data.presentation
        ? {
            ...DEFAULT_PRESENTATION,
            navigation: data.presentation.navigation,
            dashboardDefault: data.presentation.dashboard_default?.entries ?? null,
            desktopInstallPrompt: data.presentation.desktop_install_prompt,
            productNotices: data.presentation.product_notices,
          }
        : DEFAULT_PRESENTATION;
  const presentation: ConsolePresentationOptions = error
    ? {
        ...policy,
        pending: false,
        problem: true,
        retry: () => {
          void refetch();
        },
      }
    : { ...policy, problem: false };
  return (
    <ChatHomeContext.Provider value={data?.effective ?? HIDDEN_CHAT_HOME}>
      <OnboardingReminderContext.Provider value={reminders}>
        <ChatCostContext.Provider value={!error && !!data && (data.costs?.effective ?? true)}>
          <ConsolePresentationContext.Provider value={presentation}>
            {children}
          </ConsolePresentationContext.Provider>
        </ChatCostContext.Provider>
      </OnboardingReminderContext.Provider>
    </ChatHomeContext.Provider>
  );
}
export function useChatHomeOptions(): ChatHomeOptions {
  return useContext(ChatHomeContext);
}

export function useOnboardingReminderPolicy(): OnboardingReminderOptions {
  return useContext(OnboardingReminderContext);
}

export function useChatCostsVisible(): boolean {
  return useContext(ChatCostContext);
}

export function useConsolePresentation(): ConsolePresentationOptions {
  return useContext(ConsolePresentationContext);
}
