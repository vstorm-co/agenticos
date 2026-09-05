/**
 * The claims a JWT carries, read without checking its signature.
 *
 * For one question only: what does this browser's cookie *say* it is? The BFF
 * has no key to verify with and does not need one here - the backend verifies
 * every token it is handed, and a forged claim can only make the caller's own
 * refresh be refused. Never use this to decide what a token is allowed to do.
 */
export function unverifiedClaims(token: string): Record<string, unknown> | null {
  const payload = token.split(".")[1];
  if (!payload) return null;
  try {
    const json = Buffer.from(payload, "base64url").toString("utf8");
    const parsed: unknown = JSON.parse(json);
    return parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/** Whether a token is an impersonation: one that names an actor behind its subject. */
export function isImpersonation(token: string): boolean {
  return Boolean(unverifiedClaims(token)?.act);
}
