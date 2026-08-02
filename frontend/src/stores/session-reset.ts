"use client";

import { useAgentSelectionStore } from "./agent-selection-store";
import { useChatStore } from "./chat-store";
import { useConversationStore } from "./conversation-store";
import { useFilePreviewStore } from "./file-preview-store";
import { useOrgStore } from "./org-store";
import { useSourcesPanelStore } from "./sources-panel-store";

/**
 * Empty every store holding something that belonged to one signed-in account.
 *
 * Clearing the React Query cache is only half of it. These stores live in
 * module scope - two of them in `localStorage` - so a sign-out followed by a
 * sign-in in the same tab left the second account looking at the first one's
 * open conversation, its streamed messages, the file it had open, and a
 * selected organization and agent it may not even be a member of.
 *
 * Called where the query cache is cleared, and for the same reason: this state
 * belongs to a session, not to a browser.
 *
 * What is deliberately left alone is anything about the browser rather than the
 * account - the theme, and whether a sidebar is collapsed. Signing out is not a
 * reason to switch somebody back to light mode.
 */
export function resetSessionState(): void {
  useConversationStore.getState().reset();
  useChatStore.getState().clearMessages();
  useChatStore.getState().setStreaming(false);
  useFilePreviewStore.getState().close();
  useSourcesPanelStore.getState().close();
  // `refusedOrgIds` too, not only the selection: a refusal is a fact about one
  // account, and leaving it behind filters an organization out of the next
  // account's automatic pick even where that account is a member in good
  // standing.
  useOrgStore.setState({ activeOrgId: null, refusedOrgIds: [] });
  useAgentSelectionStore.getState().select(null);
  useAgentSelectionStore.getState().setDefault(null);
}
