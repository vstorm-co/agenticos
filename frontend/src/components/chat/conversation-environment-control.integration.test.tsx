import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useWebSocket } from "@/hooks/use-websocket";
import type { ConversationEnvironment } from "@/lib/conversation-environments-api";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { ConversationEnvironmentView } from "./conversation-environment-view";
const socket = vi.hoisted(() => ({ connect: vi.fn(), disconnect: vi.fn(), sendMessage: vi.fn() }));
let options: Parameters<typeof useWebSocket>[0];
vi.mock("@/hooks/use-websocket", () => ({
  useWebSocket: (value: Parameters<typeof useWebSocket>[0]) => {
    options = value;
    return socket;
  },
}));
vi.mock("@/components/public-config/public-config-provider", () => ({
  usePublicConfig: () => ({ wsUrl: "ws://console.example" }),
}));
const environment: ConversationEnvironment = {
  id: "33333333-3333-4333-8333-333333333333",
  agent_id: "11111111-1111-4111-8111-111111111111",
  kind: "desktop",
  execution_target: "agent",
  state: "ready",
  control: "none",
  can_control: true,
  expires_at: null,
  refusal: null,
  session_lifetime: "conversation",
  idle_seconds: 900,
};
function emit(value: unknown) {
  act(() => options.onMessage?.(new MessageEvent("message", { data: JSON.stringify(value) })));
}
function event(kind: string, extra: Record<string, unknown> = {}) {
  emit({ type: "browser_event", data: { kind, call_id: environment.id, step: 1, ...extra } });
}
function state(extra: Partial<ConversationEnvironment> = {}) {
  emit({ type: "environment_state", data: { ...environment, ...extra } });
}
function open(kind: ConversationEnvironment["kind"] = "desktop") {
  render(
    <ConversationEnvironmentView
      conversationId="chat"
      environment={{ ...environment, kind }}
      visible
      onState={vi.fn().mockResolvedValue(undefined)}
      onStart={vi.fn()}
      onEnd={vi.fn()}
      onRefresh={vi.fn()}
      isStarting={false}
      isEnding={false}
    />,
  );
  state({ kind });
  event("browser_opened");
  event("browser_frame", { image: "data:image/jpeg;base64,AA==", title: "Desktop" });
}
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({
    accessToken: "token",
    sessionOwnerId: "owner",
    user: { id: "owner", email: "owner@example.com", is_active: true, created_at: "2026-01-01" },
  });
  useOrgStore.setState({ activeOrgId: "org" });
});
it("acknowledges this socket's takeover, forwards typing and returns to observation", async () => {
  open();
  await userEvent.click(screen.getByRole("button", { name: "Take over" }));
  expect(socket.sendMessage).toHaveBeenLastCalledWith({ type: "take_over" });
  state({ control: "human" });
  expect(screen.queryByRole("button", { name: "Hand it back" })).not.toBeInTheDocument();
  event("browser_held", { by_user_id: "owner" });
  expect(screen.getByRole("button", { name: "Hand it back" })).toBeInTheDocument();
  fireEvent.keyDown(screen.getByRole("application"), { key: "x" });
  expect(socket.sendMessage).toHaveBeenLastCalledWith({ type: "type", text: "x" });
  await userEvent.click(screen.getByRole("button", { name: "Hand it back" }));
  expect(socket.sendMessage).toHaveBeenLastCalledWith({ type: "give_back", remember: false });
  event("browser_released");
  state();
  expect(screen.getByRole("button", { name: "Take over" })).toBeInTheDocument();
  socket.sendMessage.mockClear();
  fireEvent.keyDown(screen.getByRole("application"), { key: "y" });
  expect(socket.sendMessage).not.toHaveBeenCalled();
});
it("does not give another holder, agent control or a forbidden socket interactive input", () => {
  open();
  state({ control: "human" });
  event("browser_held", { by_user_id: "another-owner", by: "Another owner" });
  expect(screen.queryByRole("button", { name: "Hand it back" })).not.toBeInTheDocument();
  socket.sendMessage.mockClear();
  fireEvent.keyDown(screen.getByRole("application"), { key: "x" });
  expect(socket.sendMessage).not.toHaveBeenCalled();
  event("browser_released");
  state({ control: "agent", can_control: false });
  expect(screen.queryByRole("button", { name: "Take over" })).not.toBeInTheDocument();
  act(() => options.onClose?.(new CloseEvent("close", { code: 4403 })));
  expect(screen.queryByRole("application")).not.toBeInTheDocument();
});

it("fits idle and acknowledged browsers, not equivalent authority frames that only update expiry", () => {
  open("browser");
  const resizes = () =>
    socket.sendMessage.mock.calls.filter(([command]) => command.type === "resize");
  expect(resizes()).toHaveLength(1);
  state({ kind: "browser", control: "human" });
  expect(resizes()).toHaveLength(1);
  event("browser_held", { by_user_id: "owner" });
  expect(resizes()).toHaveLength(2);
  for (const day of [1, 2, 3]) {
    state({ kind: "browser", control: "human", expires_at: `2026-12-0${day}T00:00:00Z` });
  }
  expect(resizes()).toHaveLength(2);
});
