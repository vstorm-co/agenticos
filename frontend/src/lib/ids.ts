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
 * needs. A submitted prompt also sends its id as a correlation value scoped
 * by conversation and author; database rows still get the server's own ids.
 */
export function clientId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `id-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Mint a UUID for API fields that require one, including on a plain-HTTP LAN. */
export function clientUuid(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();

  // getRandomValues, unlike randomUUID, is available outside secure contexts.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const view = new DataView(bytes.buffer);
  view.setUint8(6, (view.getUint8(6) & 0x0f) | 0x40);
  view.setUint8(8, (view.getUint8(8) & 0x3f) | 0x80);
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join("-");
}
