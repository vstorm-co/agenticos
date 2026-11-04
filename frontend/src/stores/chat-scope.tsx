"use client";

import { useState, type ReactNode } from "react";

import { createAgentSelectionStore } from "./agent-selection-store";
import { createBrowserPanelStore } from "./browser-panel-store";
import { createChatStore } from "./chat-store";
import { ChatScopeContext, type ChatScopeStores } from "./chat-scope-context";
import { createConversationStore } from "./conversation-store";
import { createFilePreviewStore } from "./file-preview-store";
import { createSourcesPanelStore } from "./sources-panel-store";

/**
 * A conversation with its own stores, rendered inside the console (#2063, #2074).
 *
 * Everything under it - the chat, its socket, its approval and question cards,
 * its panels - reads and writes this scope's copies, so the Architect's window
 * and the Builder's test panel can sit beside the main chat without either one
 * overwriting the other. Its conversation is addressed to `agentId` from the
 * first render; keyed by whoever renders it to start a clean one.
 */
export function ChatScope({ agentId, children }: { agentId: string | null; children: ReactNode }) {
  const [stores] = useState<ChatScopeStores>(() => ({
    chat: createChatStore(),
    conversation: createConversationStore(),
    agentSelection: createAgentSelectionStore(agentId),
    filePreview: createFilePreviewStore(),
    browserPanel: createBrowserPanelStore(),
    sourcesPanel: createSourcesPanelStore(),
  }));
  return <ChatScopeContext.Provider value={stores}>{children}</ChatScopeContext.Provider>;
}
