"use client";

import { useAgentSelectionStore } from "./agent-selection-store";
import { useChatStore } from "./chat-store";
import { useConversationStore } from "./conversation-store";
import { useFilePreviewStore } from "./file-preview-store";
import { useOnboardingStore } from "./onboarding-store";
import { useOrgStore } from "./org-store";
import { useSourcesPanelStore } from "./sources-panel-store";

/**
 * Empty every store holding something that belonged to one organization.
 *
 * Conversations, agents, the documents behind a retrieved answer and a running
 * onboarding flow all belong to a tenant, and none of them live in the query
 * cache: they are module-scope stores, so dropping the cache on a switch does not
 * touch them. Without this, selecting another organization left the previous one's
 * open conversation, its streamed messages, the file being previewed and the
 * sources behind the last answer on screen underneath the new organization's name.
 *
 * Left alone: the theme, the sidebars, and the organization selection itself -
 * the last of these because the switch is what called this.
 */
export function resetTenantState(): void {
  useConversationStore.getState().reset();
  useChatStore.getState().clearMessages();
  useChatStore.getState().setStreaming(false);
  useFilePreviewStore.getState().close();
  // `setState`, not `close()`: closing leaves the retrieved chunks in the store,
  // and those are the previous tenant's documents. Nothing renders them while
  // the panel is shut, which is the only reason it never showed.
  useSourcesPanelStore.setState({ isOpen: false, sources: [], highlightedIndex: null });
  useAgentSelectionStore.getState().select(null);
  useAgentSelectionStore.getState().setDefault(null);
  // The guided flow is tenant-coupled too: it holds the id of an agent built in
  // this organization and the choices made getting there, so a flow left running
  // across the switch would `router.push` to the previous org's agent and land on
  // a refusal. Closing stops the coach — its `isActive` needs `isOpen` — and the
  // next `openFlow` clears the captured id and choices; the pending offer goes with
  // it, an offer minted from this org's caches having no meaning in the next.
  useOnboardingStore.getState().close();
  useOnboardingStore.getState().dismissOffer();
}

/**
 * The same, plus what belongs to the signed-in account rather than the tenant.
 *
 * Everything an organization owns is also owned by whoever was signed in, so a
 * session reset is a tenant reset and one thing more: the organization
 * selection itself, which persists to `localStorage` and would otherwise start
 * the next account inside an organization it may not be a member of.
 *
 * Called where the query cache is cleared, and for the same reason: this state
 * belongs to a session, not to a browser. What is deliberately left alone is
 * anything about the browser rather than the account - the theme, and whether a
 * sidebar is collapsed. Signing out is not a reason to switch somebody back to
 * light mode.
 */
export function resetSessionState(): void {
  resetTenantState();
  // `refusedOrgIds` too, not only the selection: a refusal is a fact about one
  // account, and leaving it behind filters an organization out of the next
  // account's automatic pick even where that account is a member in good
  // standing.
  useOrgStore.setState({ activeOrgId: null, refusedOrgIds: [] });
}
