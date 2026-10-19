"use client";

import { createContext, useContext } from "react";
import { useStore, type StoreApi, type UseBoundStore } from "zustand";

import type { AgentSelectionState } from "./agent-selection-store";
import type { BrowserPanelState } from "./browser-panel-store";
import type { ChatState } from "./chat-store";
import type { ConversationState } from "./conversation-store";
import type { FilePreviewState } from "./file-preview-store";
import type { SourcesPanelState } from "./sources-panel-store";

/** The stores a conversation on screen keeps its state in. */
export interface ChatScopeStores {
  chat: StoreApi<ChatState>;
  conversation: StoreApi<ConversationState>;
  agentSelection: StoreApi<AgentSelectionState>;
  filePreview: StoreApi<FilePreviewState>;
  browserPanel: StoreApi<BrowserPanelState>;
  sourcesPanel: StoreApi<SourcesPanelState>;
}

/**
 * A second conversation in the same document - the Architect's window, the
 * Builder's test panel - with stores of its own, so it neither reads nor
 * overwrites the main chat's. Absent, every hook reads the console's own.
 */
export const ChatScopeContext = createContext<ChatScopeStores | null>(null);

/**
 * Whether this conversation is one of those. A scoped chat owns no part of the
 * address bar: the console's `?id=` names the main chat's thread, whatever page
 * the window is open over.
 */
export function useInChatScope(): boolean {
  return useContext(ChatScopeContext) !== null;
}

/**
 * A store hook that reads the nearest scope's copy of the store, or `global`.
 *
 * `getState` / `setState` / `subscribe` stay the global store's, for the code
 * that only ever acts on the main chat - a sign-out reset, the onboarding coach.
 * Code that may run inside a scope reaches the right copy with `useApi()`.
 */
export function scopedStore<T, S extends UseBoundStore<StoreApi<T>>>(
  global: S,
  pick: (scope: ChatScopeStores) => StoreApi<T>,
) {
  function useApi(): StoreApi<T> {
    const scope = useContext(ChatScopeContext);
    return scope ? pick(scope) : global;
  }
  function useScoped(): T;
  function useScoped<U>(selector: (state: T) => U): U;
  function useScoped<U>(selector?: (state: T) => U): T | U {
    return useStore(useApi(), (state: T): T | U => (selector ? selector(state) : state));
  }
  // The global store's own API rides along whole - `persist` included, where it has one.
  const { getState, setState, subscribe, getInitialState, ...rest } = global;
  return Object.assign(useScoped, rest, { useApi, getState, setState, subscribe, getInitialState });
}
