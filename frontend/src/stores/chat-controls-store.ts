"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { useAuthStore } from "./auth-store";
import { useOrgStore } from "./org-store";
import type { LocalTarget } from "@/lib/desktop/commands";
export type ApprovalMode = "follow_agent" | "approve_all" | "ask_all";
export interface ChatControlPreferences {
  modelProfileId: string | null;
  approvalMode: ApprovalMode;
  browser: boolean;
  computer: boolean;
  localTarget: LocalTarget | null;
}
export const DEFAULT_CHAT_CONTROLS: ChatControlPreferences = {
  modelProfileId: null,
  approvalMode: "follow_agent",
  browser: false,
  computer: false,
  localTarget: null,
};
export const chatControlScope = (user: string | null | undefined, org: string | null | undefined) =>
  `${user ?? "-"}:${org ?? "-"}`;
export const currentChatControlScope = () =>
  chatControlScope(useAuthStore.getState().user?.id, useOrgStore.getState().activeOrgId);
interface State {
  byScope: Record<string, ChatControlPreferences>;
  update: (scope: string, patch: Partial<ChatControlPreferences>) => void;
}
export const useChatControlsStore = create<State>()(
  persist(
    (set) => ({
      byScope: {},
      update: (scope, patch) =>
        set((state) => ({
          byScope: {
            ...state.byScope,
            [scope]: { ...DEFAULT_CHAT_CONTROLS, ...state.byScope[scope], ...patch },
          },
        })),
    }),
    { name: "chat-controls" },
  ),
);
export const readChatControlPreferences = () =>
  useChatControlsStore.getState().byScope[currentChatControlScope()] ?? DEFAULT_CHAT_CONTROLS;
export const saveChatControlPreferences = (patch: Partial<ChatControlPreferences>) =>
  useChatControlsStore.getState().update(currentChatControlScope(), patch);
