const SESSION_CHANGED = "agenticos:transfer-session";

export function subscribeTransferSessions(listener: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener("storage", listener);
  window.addEventListener(SESSION_CHANGED, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(SESSION_CHANGED, listener);
  };
}

/** Only an operation ID is retained. Its owner and every resource are reauthorized by the API. */
export function transferSessionKey(
  org: string | null,
  user: string | null,
  scope?: string,
): string | null {
  return org && user && scope ? `agenticos:transfer:${JSON.stringify([org, user, scope])}` : null;
}

export function readTransferSession(key: string | null): string | null {
  if (!key || typeof window === "undefined") return null;
  try {
    const id = window.sessionStorage.getItem(key);
    return id && /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id) ? id : null;
  } catch {
    // Storage is optional; the operation still works in memory when the browser refuses it.
    return null;
  }
}

export function writeTransferSession(key: string | null, id: string | null): void {
  if (!key || typeof window === "undefined") return;
  try {
    if (id) window.sessionStorage.setItem(key, id);
    else window.sessionStorage.removeItem(key);
    window.dispatchEvent(new Event(SESSION_CHANGED));
  } catch {
    // Do not abort an admitted transfer because optional tab persistence is unavailable.
  }
}
