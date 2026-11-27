import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { ConversationEnvironment } from "@/lib/conversation-environments-api";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useLiveConversationEnvironment } from "./use-live-conversation-environment";

vi.mock("@/components/public-config/public-config-provider", () => ({
  usePublicConfig: () => ({ wsUrl: "ws://console.example" }),
}));

/** Only the browser's transport boundary is replaced; both hooks run unchanged. */
class Socket {
  static instances: Socket[] = [];
  static OPEN = 1;
  static CONNECTING = 0;
  readyState = Socket.CONNECTING;
  onopen: (() => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => {
    this.readyState = 3;
  });
  constructor(
    readonly url: string,
    readonly protocols?: string[],
  ) {
    Socket.instances.push(this);
  }
  open() {
    this.readyState = Socket.OPEN;
    this.onopen?.();
  }
  emit(value: unknown) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(value) }));
  }
}
const environment: ConversationEnvironment = {
  id: "33333333-3333-4333-8333-333333333333",
  agent_id: "11111111-1111-4111-8111-111111111111",
  kind: "browser",
  execution_target: "agent",
  state: "ready",
  control: "human",
  can_control: true,
  expires_at: null,
  refusal: null,
  session_lifetime: "conversation",
  idle_seconds: 900,
};
function state(socket: Socket) {
  socket.emit({ type: "environment_state", data: environment });
}
function event(socket: Socket, kind: string, extra: Record<string, unknown> = {}) {
  socket.emit({
    type: "browser_event",
    data: { kind, call_id: environment.id, step: 1, ...extra },
  });
}
beforeEach(() => {
  vi.useFakeTimers();
  Socket.instances = [];
  vi.stubGlobal("WebSocket", Socket);
  useAuthStore.setState({
    accessToken: "session",
    sessionOwnerId: "owner",
    user: {
      id: "owner",
      email: "owner@example.com",
      is_active: true,
      created_at: "2026-01-01",
    },
  });
  useOrgStore.setState({ activeOrgId: "org" });
});
afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("replaces a deferred-close socket on quick hide/show and waits for its own new control ACK", () => {
  const { result, rerender, unmount } = renderHook(
    ({ visible }) => useLiveConversationEnvironment("chat", environment, visible),
    { initialProps: { visible: true } },
  );
  expect(Socket.instances).toHaveLength(1);
  const first = Socket.instances[0]!;
  act(() => {
    first.open();
    state(first);
    event(first, "browser_opened");
    event(first, "browser_frame", { image: "data:image/jpeg;base64,AA==" });
    event(first, "browser_held", { by_user_id: "owner" });
  });
  expect(result.current.browse?.heldById).toBe("owner");
  const oldMessage = first.onmessage;
  rerender({ visible: false });
  // No timer advance: the real transport's 150ms deferred close is still pending.
  expect(first.close).not.toHaveBeenCalled();
  expect(result.current.browse?.image).toBe("data:image/jpeg;base64,AA==");
  rerender({ visible: true });
  expect(Socket.instances).toHaveLength(2);
  expect(first.close).toHaveBeenCalledOnce();
  const second = Socket.instances[1]!;
  expect(second.url).toBe(first.url);
  expect(second.protocols).toEqual(["access_token.session", "environment"]);
  expect(result.current.status).toBe("connecting");
  act(() => {
    oldMessage?.(
      new MessageEvent("message", {
        data: JSON.stringify({
          type: "browser_event",
          data: { kind: "browser_held", call_id: environment.id, step: 2, by_user_id: "owner" },
        }),
      }),
    );
    result.current.send({ type: "type", text: "stale" });
  });
  expect(second.send).not.toHaveBeenCalled();
  expect(result.current.browse?.heldById).toBeNull();
  act(() => {
    second.open();
    state(second);
    event(second, "browser_opened");
  });
  expect(result.current.status).toBe("live");
  act(() => result.current.send({ type: "type", text: "global human is not this socket" }));
  expect(second.send).not.toHaveBeenCalled();
  act(() => event(second, "browser_held", { by_user_id: "owner" }));
  act(() => result.current.send({ type: "type", text: "fresh" }));
  expect(second.send).toHaveBeenCalledExactlyOnceWith(
    JSON.stringify({ type: "type", text: "fresh" }),
  );
  unmount();
});
