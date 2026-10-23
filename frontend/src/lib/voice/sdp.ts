/**
 * The browser's half of a call's setup (#54). The offer carries one audio
 * stream and no data channel: the provider's `oai-events` channel is not
 * needed, and would let this page inject events into a session the server
 * governs. The server refuses such an offer too; this refuses before sending
 * it.
 */
export async function audioOnlyOffer(pc: RTCPeerConnection): Promise<string> {
  await pc.setLocalDescription(await pc.createOffer());
  const sdp = pc.localDescription?.sdp ?? "";
  // i18n-exempt: never shown - the caller reads any failure here as "could not connect".
  if (/^m=application/im.test(sdp)) throw new Error("An offer must not carry a data channel");
  // i18n-exempt: never shown, as above.
  if (!/^m=audio/im.test(sdp)) throw new Error("An offer must carry the microphone's audio");
  return sdp;
}

/** The console's call socket; the organization travels in the query, like the chat socket's. */
export function consoleVoiceUrl(wsOrigin: string, organizationId: string | null): string {
  const base = `${wsOrigin}/api/v1/ws/voice`;
  return organizationId ? `${base}?organization_id=${encodeURIComponent(organizationId)}` : base;
}

/** An embed's call socket (slice 2): the visitor key or the hosted page's token. */
export function embedVoiceUrl(
  wsOrigin: string,
  publicKey: string,
  visitorKey: string | null,
  token: string | null,
): string {
  const params = new URLSearchParams();
  if (visitorKey) params.set("visitor", visitorKey);
  if (token) params.set("token", token);
  const query = params.toString();
  return `${wsOrigin}/api/v1/embed/${encodeURIComponent(publicKey)}/voice/ws${query ? `?${query}` : ""}`;
}
