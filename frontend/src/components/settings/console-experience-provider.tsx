"use client";

import { createContext, useContext, type ReactNode } from "react";
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

export const ChatCostContext = createContext(true);

export const ChatHomeContext = createContext<ChatHomeOptions>(DEFAULT_CHAT_HOME);

/** Authenticated console only: public chat and embedded builders keep their own contracts. */
export function ConsoleExperienceProvider({ children }: { children: ReactNode }) {
  const { data, error } = useConsoleExperience();
  const reminders =
    !error && data ? data.reminders.effective : { enabled: false, snooze_days: 1 as const };
  return (
    <ChatHomeContext.Provider value={data?.effective ?? HIDDEN_CHAT_HOME}>
      <OnboardingReminderContext.Provider value={reminders}>
        <ChatCostContext.Provider value={!error && !!data && (data.costs?.effective ?? true)}>
          {children}
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
