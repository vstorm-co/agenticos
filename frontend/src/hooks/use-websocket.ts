"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface UseWebSocketOptions {
  url: string;
  /** The subprotocols to open with, read when a socket is actually opened.
   *
   *  A function rather than an array, because one of them carries a credential:
   *  `access_token.<jwt>` is what the handshake authenticates with, and
   *  `get_current_user_ws` verifies it once and never again - so a socket that
   *  is already up does not need the refreshed one. Passed as a value it was
   *  part of this hook's idea of *which socket this is*, and the console
   *  re-mints that token on a timer, unprompted - so a refresh closed the
   *  socket an answer was streaming on, and the server, reading that close as
   *  the reader leaving, cancelled the turn.
   *
   *  Evaluated on each `connect()` instead: a reconnect always presents the
   *  freshest token, and a refresh on its own changes nothing. */
  protocols?: () => string[] | undefined;
  onMessage?: (event: MessageEvent) => void;
  onOpen?: () => void;
  onClose?: (event: CloseEvent) => void;
  onError?: (error: Event) => void;
  reconnect?: boolean;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
}

// Close codes that won't fix themselves by reconnecting with the same socket
// params: clean/intentional shutdowns and auth/policy rejections. Reconnecting
// on these just hammers the server (and, in Firefox, trips its built-in
// failed-reconnect throttle which then blocks every subsequent attempt locally
// before it even reaches the server). A dropped connection (1006) or an
// internal server error (1011+) is worth retrying; an auth close (4001) or a
// normal close (1000) is not.
const NO_RETRY_CLOSE_CODES = new Set([1000, 1001, 1005, 1008, 4001, 4401, 4403]);

/** What identifies the socket this hook is holding.
 *
 *  The address, and only the address - which carries the organization, the one
 *  change that must not be answered by keeping the old connection. The
 *  subprotocols are deliberately absent: the only one that ever varies is the
 *  access token, and a token that changed is not a different socket. It is the
 *  same socket, still authenticated by the credential it shook hands with. */
const sigOf = (url: string) => JSON.stringify({ url });

/** Detach handlers before closing so a deliberate teardown can't re-enter the
 *  onclose logic (reconnect / token refresh) for a socket we're discarding. */
function silentClose(ws: WebSocket) {
  ws.onopen = null;
  ws.onmessage = null;
  ws.onclose = null;
  ws.onerror = null;
  try {
    ws.close();
  } catch {
    // already closing/closed - nothing to do
  }
}

export function useWebSocket({
  url,
  protocols,
  onMessage,
  onOpen,
  onClose,
  onError,
  reconnect = true,
  reconnectInterval = 1500,
  maxReconnectAttempts = 8,
}: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  // Params the live socket was opened with - lets connect() tell a StrictMode
  // remount / quick nav-back (same params → reuse the socket) apart from a real
  // change like switching organization (different params → swap the socket).
  // A refreshed token is deliberately not such a change; see `protocols`.
  const wsSigRef = useRef<string | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  // Deferred teardown timer. disconnect() schedules the close instead of doing
  // it inline so an immediate remount can cancel it and keep the live socket -
  // abruptly closing a still-connecting socket is exactly what trips Firefox's
  // reconnect throttle and looks like "the request never reached the server".
  const closeTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  // Distinguishes a deliberate disconnect (don't reconnect) from a dropped
  // connection (do reconnect). Set true on connect(), false on disconnect().
  const shouldReconnectRef = useRef(false);

  // Use refs for callbacks to avoid recreating connect function
  const onMessageRef = useRef(onMessage);
  const onOpenRef = useRef(onOpen);
  const onCloseRef = useRef(onClose);
  const onErrorRef = useRef(onError);
  // Here for the same reason the four above are, and it is what keeps a token
  // refresh out of `connect`'s identity: read through the ref, the getter is
  // not a dependency, so a new one does not rebuild `connect` and re-run the
  // caller's lifecycle effect. Seeded rather than left undefined because the
  // first `connect()` can run before this effect has flushed.
  const protocolsRef = useRef(protocols);

  useEffect(() => {
    onMessageRef.current = onMessage;
    onOpenRef.current = onOpen;
    onCloseRef.current = onClose;
    onErrorRef.current = onError;
    protocolsRef.current = protocols;
  }, [onMessage, onOpen, onClose, onError, protocols]);

  // `connect` reconnects by calling itself from a timeout, and a `useCallback`
  // cannot reference its own binding before it exists. Held in a ref, kept
  // current by the effect below: the timeout fires long after render, so it
  // reads whichever `connect` is newest rather than the one captured when the
  // socket dropped. Seeding the ref with `connect` instead of a placeholder
  // would read better, but the compiler then treats the ref as derived from a
  // memo and refuses the write that keeps it current.
  /* v8 ignore next -- a reconnect can only be scheduled by a socket `connect` opened, so the effect has run */
  const connectRef = useRef<() => void>(() => {});

  const connect = useCallback(() => {
    // A pending deferred close means we're mid-teardown; cancel it - we're
    // (re)connecting again, so don't drop the socket out from under ourselves.
    if (closeTimeoutRef.current) {
      clearTimeout(closeTimeoutRef.current);
      closeTimeoutRef.current = null;
    }

    const sig = sigOf(url);
    const live = wsRef.current;

    // Same params + live socket → reuse it (StrictMode double-mount, fast
    // navigate-back). Reconnecting here would needlessly churn the connection.
    if (
      live &&
      wsSigRef.current === sig &&
      (live.readyState === WebSocket.OPEN || live.readyState === WebSocket.CONNECTING)
    ) {
      shouldReconnectRef.current = true;
      return;
    }

    // The address changed (an organization switch), or a stale socket lingers →
    // discard it silently before opening the replacement.
    if (live) {
      silentClose(live);
      wsRef.current = null;
    }

    shouldReconnectRef.current = true;
    // Read here rather than captured: this is the one moment the credential is
    // used, so reading it now is what lets a refreshed token reach the *next*
    // handshake without disturbing the live one.
    const opening = protocolsRef.current?.();
    const ws = opening && opening.length > 0 ? new WebSocket(url, opening) : new WebSocket(url);
    wsRef.current = ws;
    wsSigRef.current = sig;

    ws.onopen = () => {
      setIsConnected(true);
      reconnectAttemptsRef.current = 0;
      onOpenRef.current?.();
    };

    ws.onmessage = (event) => {
      onMessageRef.current?.(event);
    };

    ws.onclose = (event) => {
      setIsConnected(false);

      // A deliberate disconnect() (unmount, logout, token swap) is not a failure
      // - don't surface it to the consumer (which would e.g. fire a token
      // refresh) and don't reconnect.
      if (!shouldReconnectRef.current) return;

      onCloseRef.current?.(event);

      // Auth/policy/clean closes won't recover by retrying the same socket.
      if (NO_RETRY_CLOSE_CODES.has(event.code)) return;

      if (reconnect && reconnectAttemptsRef.current < maxReconnectAttempts) {
        // Exponential backoff (capped) so a flapping/restarting server isn't
        // hammered, and the console isn't flooded with failed-connection noise.
        const delay = Math.min(reconnectInterval * 2 ** reconnectAttemptsRef.current, 15000);
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectAttemptsRef.current += 1;
          connectRef.current();
        }, delay);
      }
    };

    ws.onerror = (error) => {
      onErrorRef.current?.(error);
    };
  }, [url, reconnect, reconnectInterval, maxReconnectAttempts]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false;
    reconnectAttemptsRef.current = 0;
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    const ws = wsRef.current;
    if (!ws) return;

    // Defer the actual close so a StrictMode remount (or fast navigate-back) can
    // cancel it in connect() and reuse the live socket instead of tearing down a
    // connection that's about to be re-requested.
    if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
    closeTimeoutRef.current = setTimeout(() => {
      closeTimeoutRef.current = null;
      if (wsRef.current === ws) {
        wsRef.current = null;
        wsSigRef.current = null;
      }
      silentClose(ws);
    }, 150);
  }, []);

  const sendMessage = useCallback((data: string | object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const message = typeof data === "string" ? data : JSON.stringify(data);
      wsRef.current.send(message);
    }
  }, []);

  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return {
    isConnected,
    connect,
    disconnect,
    sendMessage,
  };
}
