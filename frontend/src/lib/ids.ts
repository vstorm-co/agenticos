/**
 * Ids minted in the browser, for rows the server has not answered for yet.
 *
 * A streamed message, a queued send and a message part all exist on screen
 * before the backend has given them an id, and something has to key them until
 * it does - `ChatMessage.isTemporaryId` marks the ones still waiting.
 *
 * **Why not `crypto.randomUUID()` alone.** It is only defined in a secure
 * context, so a deployment served over plain HTTP on anything other than
 * `localhost` - a LAN address, an embedded widget on an internal host - has no
 * `randomUUID` at all. Chat is the first thing that would break there, and it
 * would break with a `TypeError` rather than a degraded id. The fallback is
 * uniqueness without the cryptographic guarantee, which is all a local key
 * needs: these ids never leave the tab and are replaced by the server's own.
 */
export function clientId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `id-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
