import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useWebSocket } from "./use-websocket";

/**
 * A fake socket. Nothing here is a real connection: what the hook has to get
 * right is which socket it keeps and when it retries, and both are decided
 * entirely by the handlers it attaches.
 */
class FakeSocket {
  static instances: FakeSocket[] = [];
  static OPEN = 1;
  static CONNECTING = 0;

  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((error: Event) => void) | null = null;
  readyState = 1;
  close = vi.fn();
  send = vi.fn();

  constructor(
    readonly url: string,
    readonly protocols?: string[],
  ) {
    FakeSocket.instances.push(this);
  }

  /** What the browser does when the connection is established. */
  open() {
    this.onopen?.();
  }

  /** What the browser does when it drops or is closed by the server. */
  drop(code: number) {
    // A closed socket reports CLOSED, which is what tells `connect()` there is
    // nothing to reuse.
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }
}

const sockets = () => FakeSocket.instances;
const latest = () => FakeSocket.instances[FakeSocket.instances.length - 1]!;

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/**
 * The chat's socket.
 *
 * Every rule in here is about not churning the connection, and each one was
 * added because of a symptom rather than a theory.
 *
 * A remount with the same parameters reuses the live socket - React's
 * StrictMode mounts twice, and a fast navigate-back does the same thing, and
 * tearing down a still-connecting socket is exactly what trips Firefox's
 * failed-reconnect throttle. That throttle blocks every later attempt locally,
 * so the symptom is "the request never reached the server".
 *
 * Teardown is deferred for the same reason, and a deliberate disconnect is not
 * reported to the consumer at all: `onClose` fires a token refresh, and firing
 * one on unmount would refresh on every navigation.
 *
 * Auth and clean closes are never retried. Retrying a 4001 hammers the server
 * with a credential it has already refused.
 */
describe("connecting", () => {
  it("opens a socket with the protocols it was given", () => {
    const { result } = renderHook(() =>
      useWebSocket({ url: "wss://api/chat", protocols: ["access_token.t-1", "chat"] }),
    );

    act(() => result.current.connect());

    expect(sockets()).toHaveLength(1);
    expect(latest().url).toBe("wss://api/chat");
    expect(latest().protocols).toEqual(["access_token.t-1", "chat"]);
  });

  it("opens one without protocols when there are none", () => {
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat", protocols: [] }));

    act(() => result.current.connect());

    expect(latest().protocols).toBeUndefined();
  });

  it("says it is connected once the socket opens, and not before", () => {
    const onOpen = vi.fn();
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat", onOpen }));
    act(() => result.current.connect());
    expect(result.current.isConnected).toBe(false);

    act(() => latest().open());

    expect(result.current.isConnected).toBe(true);
    expect(onOpen).toHaveBeenCalled();
  });

  it("hands every frame to the consumer", () => {
    const onMessage = vi.fn();
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat", onMessage }));
    act(() => result.current.connect());

    const frame = { data: '{"type":"text_delta"}' } as MessageEvent;
    act(() => latest().onmessage!(frame));

    expect(onMessage).toHaveBeenCalledWith(frame);
  });

  it("hands an error to the consumer", () => {
    const onError = vi.fn();
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat", onError }));
    act(() => result.current.connect());

    const failure = new Event("error");
    act(() => latest().onerror!(failure));

    expect(onError).toHaveBeenCalledWith(failure);
  });

  it("reuses a live socket when nothing changed", () => {
    // StrictMode mounts twice, and a fast navigate-back looks the same.
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat" }));
    act(() => result.current.connect());
    act(() => latest().open());

    act(() => result.current.connect());

    expect(sockets()).toHaveLength(1);
  });

  it("reuses a socket that is still connecting", () => {
    // Closing one mid-handshake is what trips the browser's own throttle.
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat" }));
    act(() => result.current.connect());
    latest().readyState = FakeSocket.CONNECTING;

    act(() => result.current.connect());

    expect(sockets()).toHaveLength(1);
  });

  it("swaps the socket when the token changes", () => {
    // A refreshed access token arrives as a different subprotocol, and the old
    // socket is authenticated with a credential that is about to expire.
    const { result, rerender } = renderHook(
      ({ token }: { token: string }) =>
        useWebSocket({ url: "wss://api/chat", protocols: [`access_token.${token}`] }),
      { initialProps: { token: "t-1" } },
    );
    act(() => result.current.connect());
    act(() => latest().open());
    const first = latest();

    rerender({ token: "t-2" });
    act(() => result.current.connect());

    expect(sockets()).toHaveLength(2);
    expect(latest().protocols).toEqual(["access_token.t-2"]);
    // Discarded silently: its handlers are detached first, so its close cannot
    // re-enter the reconnect logic for a socket nobody wants.
    expect(first.onclose).toBeNull();
    expect(first.close).toHaveBeenCalled();
  });

  it("replaces a socket that is neither open nor connecting", () => {
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat" }));
    act(() => result.current.connect());
    latest().readyState = 3;

    act(() => result.current.connect());

    expect(sockets()).toHaveLength(2);
  });

  it("survives a socket that throws on close", () => {
    // Closing an already-closing socket throws in some browsers, and the
    // replacement still has to be opened.
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat" }));
    act(() => result.current.connect());
    latest().readyState = 3;
    latest().close.mockImplementation(() => {
      throw new Error("already closing");
    });

    act(() => result.current.connect());

    expect(sockets()).toHaveLength(2);
  });
});

describe("reconnecting", () => {
  it("retries a dropped connection, backing off each time", () => {
    const { result } = renderHook(() =>
      useWebSocket({ url: "wss://api/chat", reconnectInterval: 100 }),
    );
    act(() => result.current.connect());

    act(() => latest().drop(1006));
    act(() => vi.advanceTimersByTime(100));
    expect(sockets()).toHaveLength(2);

    // The second wait is twice the first: a flapping server is not hammered.
    act(() => latest().drop(1006));
    act(() => vi.advanceTimersByTime(100));
    expect(sockets()).toHaveLength(2);
    act(() => vi.advanceTimersByTime(100));
    expect(sockets()).toHaveLength(3);
  });

  it("caps the backoff rather than waiting minutes", () => {
    const { result } = renderHook(() =>
      useWebSocket({ url: "wss://api/chat", reconnectInterval: 10_000, maxReconnectAttempts: 8 }),
    );
    act(() => result.current.connect());

    act(() => latest().drop(1006));
    act(() => vi.advanceTimersByTime(10_000));
    act(() => latest().drop(1006));
    act(() => vi.advanceTimersByTime(15_000));

    expect(sockets()).toHaveLength(3);
  });

  it("starts the backoff over once a socket opens", () => {
    // Otherwise a connection that drops once an hour eventually waits fifteen
    // seconds to recover from its first failure.
    const { result } = renderHook(() =>
      useWebSocket({ url: "wss://api/chat", reconnectInterval: 100 }),
    );
    act(() => result.current.connect());
    act(() => latest().drop(1006));
    act(() => vi.advanceTimersByTime(100));
    act(() => latest().open());

    act(() => latest().drop(1006));
    act(() => vi.advanceTimersByTime(100));

    expect(sockets()).toHaveLength(3);
  });

  it("gives up after the attempt limit", () => {
    const { result } = renderHook(() =>
      useWebSocket({ url: "wss://api/chat", reconnectInterval: 1, maxReconnectAttempts: 2 }),
    );
    act(() => result.current.connect());

    for (let attempt = 0; attempt < 5; attempt += 1) {
      act(() => latest().drop(1006));
      act(() => vi.advanceTimersByTime(1000));
    }

    expect(sockets()).toHaveLength(3);
  });

  it("never retries an auth close, however retryable the rest are", () => {
    // The credential has already been refused; retrying it is a loop the server
    // pays for.
    for (const code of [1000, 1001, 1005, 1008, 4001, 4401, 4403]) {
      FakeSocket.instances = [];
      const { result } = renderHook(() =>
        useWebSocket({ url: "wss://api/chat", reconnectInterval: 1 }),
      );
      act(() => result.current.connect());

      act(() => latest().drop(code));
      act(() => vi.advanceTimersByTime(1000));

      expect(sockets(), `close code ${code}`).toHaveLength(1);
    }
  });

  it("does not retry when the caller asked it not to", () => {
    const { result } = renderHook(() =>
      useWebSocket({ url: "wss://api/chat", reconnect: false, reconnectInterval: 1 }),
    );
    act(() => result.current.connect());

    act(() => latest().drop(1006));
    act(() => vi.advanceTimersByTime(1000));

    expect(sockets()).toHaveLength(1);
  });

  it("reports a drop to the consumer, which is what refreshes the token", () => {
    const onClose = vi.fn();
    const { result } = renderHook(() =>
      useWebSocket({ url: "wss://api/chat", onClose, reconnect: false }),
    );
    act(() => result.current.connect());

    act(() => latest().drop(1006));

    expect(onClose).toHaveBeenCalledWith(expect.objectContaining({ code: 1006 }));
    expect(result.current.isConnected).toBe(false);
  });
});

describe("disconnecting", () => {
  it("defers the close, so an immediate remount keeps the socket", () => {
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat" }));
    act(() => result.current.connect());
    act(() => latest().open());
    const socket = latest();

    act(() => result.current.disconnect());
    act(() => result.current.connect());
    act(() => vi.advanceTimersByTime(1000));

    expect(socket.close).not.toHaveBeenCalled();
    expect(sockets()).toHaveLength(1);
  });

  it("closes the socket once the deferral elapses", () => {
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat" }));
    act(() => result.current.connect());
    const socket = latest();

    act(() => result.current.disconnect());
    act(() => vi.advanceTimersByTime(150));

    expect(socket.close).toHaveBeenCalled();
  });

  it("says nothing to the consumer about a deliberate disconnect", () => {
    // `onClose` fires a token refresh; firing one on every unmount would refresh
    // on every navigation.
    const onClose = vi.fn();
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat", onClose }));
    act(() => result.current.connect());

    act(() => result.current.disconnect());
    act(() => latest().drop(1006));

    expect(onClose).not.toHaveBeenCalled();
  });

  it("cancels a pending retry, so a closed tab stops trying", () => {
    const { result } = renderHook(() =>
      useWebSocket({ url: "wss://api/chat", reconnectInterval: 100 }),
    );
    act(() => result.current.connect());
    act(() => latest().drop(1006));

    act(() => result.current.disconnect());
    act(() => vi.advanceTimersByTime(1000));

    expect(sockets()).toHaveLength(1);
  });

  it("does nothing when there was never a socket", () => {
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat" }));

    act(() => result.current.disconnect());
    act(() => vi.advanceTimersByTime(1000));

    expect(sockets()).toEqual([]);
  });

  it("replaces its own pending teardown rather than stacking timers", () => {
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat" }));
    act(() => result.current.connect());
    const socket = latest();

    act(() => result.current.disconnect());
    act(() => result.current.disconnect());
    act(() => vi.advanceTimersByTime(150));

    expect(socket.close).toHaveBeenCalledTimes(1);
  });

  it("keeps a socket that was replaced before the teardown fired", () => {
    // The deferred close must only clear the reference if it still points at the
    // socket it was scheduled for.
    const { result, rerender } = renderHook(
      ({ token }: { token: string }) =>
        useWebSocket({ url: "wss://api/chat", protocols: [`access_token.${token}`] }),
      { initialProps: { token: "t-1" } },
    );
    act(() => result.current.connect());
    act(() => result.current.disconnect());
    rerender({ token: "t-2" });
    act(() => result.current.connect());

    act(() => vi.advanceTimersByTime(1000));

    expect(sockets()).toHaveLength(2);
    expect(latest().close).not.toHaveBeenCalled();
  });

  it("tears the socket down when the component goes away", () => {
    const { result, unmount } = renderHook(() => useWebSocket({ url: "wss://api/chat" }));
    act(() => result.current.connect());
    const socket = latest();

    unmount();
    act(() => vi.advanceTimersByTime(150));

    expect(socket.close).toHaveBeenCalled();
  });
});

describe("sending", () => {
  it("sends an object as JSON and a string as itself", () => {
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat" }));
    act(() => result.current.connect());
    act(() => latest().open());

    act(() => result.current.sendMessage({ type: "message", content: "hi" }));
    act(() => result.current.sendMessage("ping"));

    expect(latest().send).toHaveBeenNthCalledWith(1, '{"type":"message","content":"hi"}');
    expect(latest().send).toHaveBeenNthCalledWith(2, "ping");
  });

  it("drops a message when the socket is not open", () => {
    // The composer is disabled on `isConnected`, but a queued send can still
    // land during a reconnect - and `send` on a closed socket throws.
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat" }));
    act(() => result.current.connect());
    latest().readyState = 3;

    act(() => result.current.sendMessage("ping"));

    expect(latest().send).not.toHaveBeenCalled();
  });

  it("sends nothing before there is a socket at all", () => {
    const { result } = renderHook(() => useWebSocket({ url: "wss://api/chat" }));

    act(() => result.current.sendMessage("ping"));

    expect(sockets()).toEqual([]);
  });
});
