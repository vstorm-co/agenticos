import { useState, type ComponentProps } from "react";
import type { ConversationEnvironmentView } from "./conversation-environment-view";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useConversationEnvironments } from "@/hooks/use-conversation-environments";
import type { ConversationEnvironment } from "@/lib/conversation-environments-api";
import { ChatWorkspaceProvider } from "./chat-workspace-context";
import { ConversationEnvironments } from "./conversation-environments";

vi.mock("@/hooks/use-conversation-environments", () => ({ useConversationEnvironments: vi.fn() }));
vi.mock("./conversation-environment-view", () => ({
  ConversationEnvironmentView: ({
    onStart,
    onEnd,
    onState,
    onRefresh,
    environment: current,
  }: ComponentProps<typeof ConversationEnvironmentView>) => (
    <>
      <button onClick={() => void onStart()}>Prepare test environment</button>
      <button onClick={() => void onEnd()}>End test environment</button>
      <button onClick={() => void onState(current)}>Receive test state</button>
      <button onClick={onRefresh}>Refresh test state</button>
    </>
  ),
}));
const agent = "11111111-1111-4111-8111-111111111111";
const panels = ["browser", "desktop"] as const;
const environment: ConversationEnvironment = {
  id: null,
  kind: "browser",
  agent_id: agent,
  execution_target: "agent",
  state: "not_started",
  session_lifetime: "conversation",
  idle_seconds: 900,
  control: "none",
  can_control: false,
  expires_at: null,
  refusal: null,
};
let api: ReturnType<typeof useConversationEnvironments>;
let prepare: () => Promise<string | null>;
function Harness({
  conversation = "chat",
  preparing = false,
}: {
  conversation?: string | null;
  preparing?: boolean;
}) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  return (
    <ChatWorkspaceProvider shared conversationId={conversation} environmentPanels={panels}>
      <div ref={setSlot} />
      <ConversationEnvironments
        conversationId={conversation}
        agentId={agent}
        panels={panels}
        target="agent"
        buttonSlot={slot}
        prepareConversation={prepare}
        preparing={preparing}
      />
    </ChatWorkspaceProvider>
  );
}
beforeEach(() => {
  api = {
    items: [environment, { ...environment, kind: "desktop" }],
    isLoading: false,
    error: null,
    refresh: vi.fn(),
    remember: vi.fn(),
    start: vi.fn().mockResolvedValue(environment),
    end: vi.fn(),
    isStarting: false,
    isEnding: false,
  };
  prepare = vi.fn().mockResolvedValue("chat");
  vi.mocked(useConversationEnvironments).mockImplementation(() => api);
});
it("opens a passive view and provisions only after the explicit start", async () => {
  render(<Harness />);
  expect(useConversationEnvironments).toHaveBeenLastCalledWith("chat", agent, false, "agent");
  await userEvent.click(screen.getByRole("button", { name: "Open workspace" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Browser" }));
  await waitFor(() => expect(prepare).toHaveBeenCalledOnce());
  expect(api.start).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Prepare test environment" }));
  expect(api.start).toHaveBeenCalledWith({ conversation: "chat", agent, kind: "browser" });
  await userEvent.click(screen.getByRole("button", { name: "Close workspace" }));
  expect(api.end).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.getByRole("button", { name: "Open workspace" })).toHaveFocus());
});
it("can file an empty chat before its first message without provisioning", async () => {
  render(<Harness conversation={null} />);
  await userEvent.click(screen.getByRole("button", { name: "Open workspace" }));
  expect(screen.getByRole("menuitem", { name: "Files" })).toHaveAttribute("aria-disabled", "true");
  await userEvent.click(screen.getByRole("menuitem", { name: "Desktop" }));
  await waitFor(() => expect(prepare).toHaveBeenCalledOnce());
  expect(screen.getByRole("status")).toHaveTextContent("Loading environment");
  expect(api.start).not.toHaveBeenCalled();
});
it("shows a failed empty-chat preparation and permits retry", async () => {
  vi.mocked(prepare).mockResolvedValueOnce(null).mockResolvedValueOnce(null);
  render(<Harness conversation={null} />);
  await userEvent.click(screen.getByRole("button", { name: "Open workspace" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Browser" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(prepare).toHaveBeenCalledTimes(2));
});
it("reports read failure and refreshes without provisioning", async () => {
  api.error = new Error("Unavailable");
  render(<Harness />);
  await userEvent.click(screen.getByRole("button", { name: "Open workspace" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Browser" }));
  await act(async () => {});
  expect(screen.getByRole("alert")).toHaveTextContent("Could not load");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(api.refresh).toHaveBeenCalledOnce();
  expect(api.start).not.toHaveBeenCalled();
});

it("can end, refresh and remember the selected desktop through its own address", async () => {
  render(<Harness />);
  await userEvent.click(screen.getByRole("button", { name: "Open workspace" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Desktop" }));
  await userEvent.click(screen.getByRole("button", { name: "End test environment" }));
  expect(api.end).toHaveBeenCalledWith({ conversation: "chat", agent, kind: "desktop" });
  await userEvent.click(screen.getByRole("button", { name: "Refresh test state" }));
  expect(api.refresh).toHaveBeenCalledOnce();
  await userEvent.click(screen.getByRole("button", { name: "Receive test state" }));
  expect(api.remember).toHaveBeenCalledWith({ ...environment, kind: "desktop" });
});
it("opens Files without creating or provisioning an environment", async () => {
  render(<Harness />);
  await userEvent.click(screen.getByRole("button", { name: "Open workspace" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Files" }));
  expect(prepare).not.toHaveBeenCalled();
  expect(api.start).not.toHaveBeenCalled();
});
it("shows a controlled failure when empty-chat creation throws", async () => {
  vi.mocked(prepare).mockRejectedValue(new Error("Private transport detail"));
  render(<Harness conversation={null} />);
  await userEvent.click(screen.getByRole("button", { name: "Open workspace" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Browser" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load");
  expect(screen.queryByText("Private transport detail")).not.toBeInTheDocument();
});
it("holds the loading geometry until a readiness read arrives", async () => {
  api.items = undefined;
  api.isLoading = true;
  render(<Harness />);
  await userEvent.click(screen.getByRole("button", { name: "Open workspace" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Browser" }));
  expect(screen.getByRole("status")).toHaveTextContent("Loading environment");
  expect(api.start).not.toHaveBeenCalled();
});
