import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import type { ConversationEnvironment } from "@/lib/conversation-environments-api";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useWebSocket } from "./use-websocket";
import { useLiveConversationEnvironment } from "./use-live-conversation-environment";

const socket = vi.hoisted(() => ({ connect: vi.fn(), disconnect: vi.fn(), sendMessage: vi.fn() }));
let options: Parameters<typeof useWebSocket>[0];
vi.mock("./use-websocket", () => ({
  useWebSocket: (received: Parameters<typeof useWebSocket>[0]) => {
    options = received;
    return socket;
  },
}));
vi.mock("@/components/public-config/public-config-provider", () => ({
  usePublicConfig: () => ({ wsUrl: "ws://console.example" }),
}));

const environment: ConversationEnvironment = {
  id: "33333333-3333-4333-8333-333333333333",
  agent_id: "11111111-1111-4111-8111-111111111111",
  kind: "browser",
  execution_target: "agent",
  state: "ready",
  control: "none",
  can_control: true,
  expires_at: null,
  refusal: null,
  session_lifetime: "conversation",
  idle_seconds: 900,
};

function emit(value: unknown): void {
  options.onMessage?.(new MessageEvent("message", { data: JSON.stringify(value) }));
}
function picture(title = "Prepared page") {
  return {
    type: "browser_event",
    data: {
      kind: "browser_frame",
      call_id: environment.id,
      step: 1,
      title,
      image: "data:image/jpeg;base64,AA==",
      run_id: null,
    },
  };
}

function opened(): void {
  emit({
    type: "browser_event",
    data: {
      kind: "browser_opened",
      call_id: environment.id,
      step: 0,
      run_id: null,
      navigable: true,
    },
  });
}

function view(title = "Prepared page"): void {
  emit({ type: "environment_state", data: environment });
  opened();
  emit(picture(title));
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({
    sessionOwnerId: "owner",
    accessToken: "initial-token",
    user: { id: "actor", email: "reader@example.com", is_active: true, created_at: "2026-01-01" },
  });
  useOrgStore.setState({ activeOrgId: "org-one" });
});

it("opens an authenticated environment socket without starting any run", () => {
  const { result, unmount } = renderHook(() =>
    useLiveConversationEnvironment("chat/one", environment, true),
  );
  expect(options.url).toBe(
    `ws://console.example/api/v1/ws/conversations/chat%2Fone/environments/${environment.id}?project_execution_target=agent`,
  );
  expect(options.protocols?.()).toEqual(["access_token.initial-token", "environment"]);
  expect(options.messageScope).toBe(options.identity);
  expect(socket.connect).toHaveBeenCalledOnce();
  expect(result.current.status).toBe("connecting");
  unmount();
  expect(socket.disconnect).toHaveBeenCalledOnce();
});

it.each([
  { enabled: false, token: "token", environment },
  { enabled: true, token: null, environment },
  { enabled: true, token: "token", environment: { ...environment, id: null } },
  { enabled: true, token: "token", environment: { ...environment, state: "starting" as const } },
])(
  "never opens an absent, hidden or unauthorized view",
  ({ enabled, token, environment: selected }) => {
    useAuthStore.setState({ accessToken: token });
    const { result } = renderHook(() => useLiveConversationEnvironment("chat", selected, enabled));
    act(() => {
      result.current.retry();
      result.current.send({ type: "take_over" });
    });
    expect(socket.connect).not.toHaveBeenCalled();
    expect(socket.sendMessage).not.toHaveBeenCalled();
  },
);

it("keeps the actual page and current driver independent of an agent run", () => {
  const { result } = renderHook(() => useLiveConversationEnvironment("chat", environment, true));
  act(() => emit({ type: "environment_state", data: { ...environment, control: "agent" } }));
  act(opened);
  act(() => emit(picture()));
  expect(result.current.environment?.control).toBe("agent");
  expect(result.current.browse?.title).toBe("Prepared page");
  expect(result.current.browse?.runId).toBeNull();
  act(() => result.current.send({ type: "take_over" }));
  expect(socket.sendMessage).not.toHaveBeenCalled();
  act(() => emit({ type: "environment_state", data: { ...environment, control: "human" } }));
  act(() => result.current.send({ type: "click", x: 1, y: 1 }));
  expect(socket.sendMessage).toHaveBeenCalledWith({ type: "click", x: 1, y: 1 });
});

it.each([
  "not json",
  JSON.stringify({ type: "browser_event", data: { ...picture().data, call_id: "another" } }),
])("closes malformed streams until the person explicitly retries", (data) => {
  const { result } = renderHook(() => useLiveConversationEnvironment("chat", environment, true));
  act(() => options.onMessage?.(new MessageEvent("message", { data })));
  expect(result.current.status).toBe("malformed");
  expect(socket.disconnect).toHaveBeenCalled();
  act(() => emit(picture()));
  expect(result.current.browse).toBeNull();
  act(() => result.current.retry());
  act(() => view());
  expect(result.current.status).toBe("live");
});

it("drops previous tenant pictures and buffered callbacks on a switch", () => {
  const { result } = renderHook(() => useLiveConversationEnvironment("chat", environment, true));
  act(() => view("Private first tenant"));
  const old = options.onMessage;
  const oldIdentity = options.identity;
  act(() => useOrgStore.setState({ activeOrgId: "org-two" }));
  expect(result.current.browse).toBeNull();
  expect(options.identity).not.toBe(oldIdentity);
  act(() =>
    old?.(new MessageEvent("message", { data: JSON.stringify(picture("Late old frame")) })),
  );
  expect(result.current.browse).toBeNull();
  act(() => view("Second tenant"));
  expect(result.current.browse?.title).toBe("Second tenant");
});

it("keeps the socket on token refresh and presents the new token on reconnect", () => {
  renderHook(() => useLiveConversationEnvironment("chat", environment, true));
  act(() => useAuthStore.setState({ accessToken: "refreshed-token" }));
  expect(socket.connect).toHaveBeenCalledOnce();
  expect(socket.disconnect).not.toHaveBeenCalled();
  expect(options.protocols?.()).toEqual(["access_token.refreshed-token", "environment"]);
});

it.each([
  [4403, "forbidden"],
  [4401, "forbidden"],
  [4404, "gone"],
  [1011, "unavailable"],
] as const)("clears the picture when the server closes with %s", (code, status) => {
  const { result } = renderHook(() => useLiveConversationEnvironment("chat", environment, true));
  act(() => view());
  act(() => options.onClose?.(new CloseEvent("close", { code })));
  expect(result.current.status).toBe(status);
  expect(result.current.browse).toBeNull();
  act(() => result.current.send({ type: "click", x: 1, y: 1 }));
  expect(socket.sendMessage).not.toHaveBeenCalled();
});

it.each([
  ["expired", "gone"],
  ["failed", "unavailable"],
  ["starting", "connecting"],
] as const)("clears the view immediately when readiness becomes %s", (state, status) => {
  const { result } = renderHook(() => useLiveConversationEnvironment("chat", environment, true));
  act(() => view());
  expect(result.current.browse).not.toBeNull();
  act(() =>
    emit({ type: "environment_state", data: { ...environment, state, can_control: false } }),
  );
  expect(result.current.status).toBe(status);
  expect(result.current.browse).toBeNull();
  expect(socket.disconnect).toHaveBeenCalled();
  act(() => result.current.send({ type: "take_over" }));
  expect(socket.sendMessage).not.toHaveBeenCalled();
});

it("stops sending as soon as the token disappears", () => {
  const { result } = renderHook(() => useLiveConversationEnvironment("chat", environment, true));
  act(() => view());
  act(() => emit({ type: "environment_state", data: { ...environment, control: "human" } }));
  act(() => useAuthStore.setState({ accessToken: null }));
  act(() => result.current.send({ type: "click", x: 1, y: 1 }));
  expect(socket.sendMessage).not.toHaveBeenCalled();
});

it("removes a stale live screen immediately when a read confirms End", () => {
  const { result, rerender } = renderHook(
    ({ selected }) => useLiveConversationEnvironment("chat", selected, true),
    { initialProps: { selected: environment } },
  );
  act(() => view());
  expect(result.current.browse).not.toBeNull();
  rerender({ selected: { ...environment, state: "expired", can_control: false } });
  expect(result.current.browse).toBeNull();
  act(() => result.current.send({ type: "click", x: 1, y: 2 }));
  expect(socket.sendMessage).not.toHaveBeenCalled();
  expect(socket.disconnect).toHaveBeenCalled();
});

it("requires an authoritative state before accepting a picture or controls", () => {
  const { result } = renderHook(() => useLiveConversationEnvironment("chat", environment, true));
  act(opened);
  act(() => emit(picture()));
  expect(result.current.browse).toBeNull();
  expect(result.current.status).toBe("connecting");
  act(() => result.current.send({ type: "take_over" }));
  expect(socket.sendMessage).not.toHaveBeenCalled();
  act(() => view());
  expect(result.current.browse).not.toBeNull();
});
it("keeps malformed streams closed despite buffered frames and a subsequent close", () => {
  const { result } = renderHook(() => useLiveConversationEnvironment("chat", environment, true));
  act(() => options.onMessage?.(new MessageEvent("message", { data: "not-json" })));
  act(() => view());
  act(() => options.onClose?.(new CloseEvent("close", { code: 1011 })));
  expect(result.current.status).toBe("malformed");
  expect(result.current.browse).toBeNull();
});
it("handles refusal before the first state without retaining another session", () => {
  useAuthStore.setState({ user: null, sessionOwnerId: null, accessToken: null });
  const { result } = renderHook(() => useLiveConversationEnvironment("chat", environment, true));
  expect(options.protocols?.()).toBeUndefined();
  act(() => options.onClose?.(new CloseEvent("close", { code: 4401 })));
  expect(result.current.status).toBe("forbidden");
  expect(result.current.environment).toBeNull();
  expect(socket.connect).not.toHaveBeenCalled();
});
