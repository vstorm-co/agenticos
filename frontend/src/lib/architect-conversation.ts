/**
 * The Architect's conversation a person last had open in an organization, kept in
 * this browser so a page load goes back to it rather than starting another.
 */

const PREFIX = "architect-conversation";

function keyOf(userId: string, organizationId: string): string {
  return `${PREFIX}:${userId}:${organizationId}`;
}

/** The conversation last open, or null when none is remembered or storage is unavailable. */
export function recallConversation(userId: string, organizationId: string): string | null {
  try {
    return localStorage.getItem(keyOf(userId, organizationId));
  } catch {
    return null;
  }
}

/** Remembers the open conversation, or forgets it when a new one is started. */
export function rememberConversation(
  userId: string,
  organizationId: string,
  conversationId: string | null,
): void {
  try {
    const key = keyOf(userId, organizationId);
    if (conversationId) localStorage.setItem(key, conversationId);
    else localStorage.removeItem(key);
  } catch {
    // Remembering is a convenience: without storage every load starts afresh.
  }
}
