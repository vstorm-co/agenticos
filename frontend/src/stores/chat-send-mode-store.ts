"use client";

import { useCallback } from "react";
import { create } from "zustand";
import { persist } from "zustand/middleware";

import { chatSendModeScope, isChatSendMode, isChatSendModeScope } from "@/lib/chat-send-mode";
import type { ChatSendMode } from "@/lib/chat-send-mode";

interface ChatSendModeState {
  /** Only small UI preferences are stored here; composer content never is. */
  byScope: Record<string, ChatSendMode>;
  setMode: (scope: string, mode: ChatSendMode) => void;
}

function validModes(value: unknown): Record<string, ChatSendMode> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return {};
  const modes: Record<string, ChatSendMode> = {};
  for (const [scope, mode] of Object.entries(value)) {
    if (isChatSendModeScope(scope) && isChatSendMode(mode)) modes[scope] = mode;
  }
  return modes;
}

export const useChatSendModeStore = create<ChatSendModeState>()(
  persist(
    (set) => ({
      byScope: {},
      setMode: (scope, mode) => {
        if (!isChatSendModeScope(scope)) return;
        set((state) => ({ byScope: { ...state.byScope, [scope]: mode } }));
      },
    }),
    {
      name: "chat-send-mode",
      partialize: (state) => ({ byScope: state.byScope }),
      merge: (persisted: unknown, current) => {
        const saved = persisted !== null && typeof persisted === "object" ? persisted : {};
        const byScope = "byScope" in saved ? validModes(saved.byScope) : {};
        return { ...current, byScope };
      },
    },
  ),
);

/** Missing identity always means Queue, and never shares another scope's choice. */
export function useChatSendModePreference(
  accountId: string | null | undefined,
  organizationId: string | null | undefined,
  agentId: string | null | undefined,
) {
  const scope = chatSendModeScope(accountId, organizationId, agentId);
  const mode = useChatSendModeStore((state) =>
    scope ? (state.byScope[scope] ?? "queue") : "queue",
  );
  const setMode = useCallback(
    (next: ChatSendMode) => {
      if (scope) useChatSendModeStore.getState().setMode(scope, next);
    },
    [scope],
  );
  return { mode, setMode };
}
