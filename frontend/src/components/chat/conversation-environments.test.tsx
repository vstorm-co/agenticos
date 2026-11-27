import { useState, type ComponentProps } from "react";
import type { QueryObserverSuccessResult } from "@tanstack/react-query";
import type { ConversationEnvironmentView } from "./conversation-environment-view";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useConversationEnvironments } from "@/hooks/use-conversation-environments";
import type {
  ConversationEnvironment,
  ConversationEnvironmentList,
} from "@/lib/conversation-environments-api";
import { ChatWorkspaceProvider, useRequiredChatWorkspace } from "./chat-workspace-context";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
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
      <div data-testid="environment-target">{current.id}</div>
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
      <RoutingControls />
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
function RoutingControls() {
  const workspace = useRequiredChatWorkspace();
  return (
    <>
      <div data-testid="routing">
        {workspace.activePanel}:{workspace.environment ?? "activity"}
      </div>
      <button onClick={() => workspace.openPanel("browser")}>Browser tab</button>
      <button onClick={() => workspace.openPanel("desktop")}>Desktop tab</button>
      <button onClick={() => workspace.showVisual("visual", false)}>Show visual</button>
    </>
  );
}
beforeEach(() => {
  useBrowserPanelStore.setState({ openCallId: null, openRequest: 0, automatic: false });
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

function readResult(
  items = api.items ?? [],
): QueryObserverSuccessResult<ConversationEnvironmentList, Error> {
  return {
    data: { items },
    dataUpdatedAt: 1,
    error: null,
    errorUpdatedAt: 0,
    failureCount: 0,
    failureReason: null,
    errorUpdateCount: 0,
    isError: false,
    isFetched: true,
    isFetchedAfterMount: true,
    isFetching: false,
    isLoading: false,
    isPending: false,
    isLoadingError: false,
    isInitialLoading: false,
    isPaused: false,
    isPlaceholderData: false,
    isRefetchError: false,
    isRefetching: false,
    isStale: false,
    isSuccess: true,
    isEnabled: true,
    status: "success",
    fetchStatus: "idle",
    refetch: api.refresh,
  };
}

it("keeps a legacy browser activity visible after a read finds no owned environment", async () => {
  useBrowserPanelStore.getState().open("legacy-call", true);
  vi.mocked(api.refresh).mockResolvedValue(readResult());
  render(<Harness />);
  await waitFor(() => expect(api.refresh).toHaveBeenCalledOnce());
  expect(screen.getByTestId("routing")).toHaveTextContent("browser:activity");
  await userEvent.click(screen.getByRole("button", { name: "Show visual" }));
  await userEvent.click(screen.getByRole("button", { name: "Browser tab" }));
  await waitFor(() => expect(api.refresh).toHaveBeenCalledTimes(2));
  expect(screen.getByTestId("routing")).toHaveTextContent("browser:activity");
  expect(
    screen.queryByRole("button", { name: "Prepare test environment" }),
  ).not.toBeInTheDocument();
  expect(api.start).not.toHaveBeenCalled();
});

it("keeps an explicit manual Browser selection when returning from Desktop", async () => {
  useBrowserPanelStore.getState().open("legacy-call", true);
  vi.mocked(api.refresh).mockResolvedValue(readResult());
  render(<Harness />);
  await userEvent.click(screen.getByRole("button", { name: "Open workspace" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Browser" }));
  expect(screen.getByTestId("routing")).toHaveTextContent("browser:browser");
  await userEvent.click(screen.getByRole("button", { name: "Desktop tab" }));
  await userEvent.click(screen.getByRole("button", { name: "Browser tab" }));
  expect(screen.getByTestId("routing")).toHaveTextContent("browser:browser");
  expect(api.start).not.toHaveBeenCalled();
});

it.each(["ready", "starting"] as const)(
  "uses the actual %s owned target only after a fresh authoritative read",
  async (state) => {
    const answer = Promise.withResolvers<Awaited<ReturnType<typeof api.refresh>>>();
    const owned = { ...environment, id: "22222222-2222-4222-8222-222222222222", state };
    api.items = [owned, { ...environment, kind: "desktop" }];
    vi.mocked(api.refresh).mockReturnValue(answer.promise);
    useBrowserPanelStore.getState().open("owned-call", true);
    render(<Harness />);
    expect(screen.getByTestId("routing")).toHaveTextContent("browser:activity");
    await act(async () => answer.resolve(readResult()));
    expect(screen.getByTestId("routing")).toHaveTextContent("browser:browser");
    expect(screen.getByTestId("environment-target")).toHaveTextContent(owned.id);
    expect(api.start).not.toHaveBeenCalled();
    expect(prepare).not.toHaveBeenCalled();
    expect(api.refresh).toHaveBeenCalledOnce();
  },
);

it.each(["Desktop tab", "Show visual"])(
  "does not preempt %s when an old readiness read completes",
  async (control) => {
    const answer = Promise.withResolvers<Awaited<ReturnType<typeof api.refresh>>>();
    vi.mocked(api.refresh).mockReturnValue(answer.promise);
    useBrowserPanelStore.getState().open("owned-call", true);
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: control }));
    const owned = {
      ...environment,
      id: "22222222-2222-4222-8222-222222222222",
      state: "ready" as const,
    };
    await act(async () => answer.resolve(readResult([owned])));
    expect(screen.getByTestId("routing")).toHaveTextContent(
      control === "Desktop tab" ? "desktop:desktop" : "visuals:activity",
    );
    expect(api.start).not.toHaveBeenCalled();
  },
);

it("rechecks a new activity call and ignores the superseded result", async () => {
  const first = Promise.withResolvers<Awaited<ReturnType<typeof api.refresh>>>();
  vi.mocked(api.refresh).mockReturnValueOnce(first.promise).mockResolvedValue(readResult());
  useBrowserPanelStore.getState().open("first-call", true);
  render(<Harness />);
  await act(async () => useBrowserPanelStore.getState().open("second-call", true));
  expect(api.refresh).toHaveBeenCalledTimes(2);
  const owned = {
    ...environment,
    id: "22222222-2222-4222-8222-222222222222",
    state: "ready" as const,
  };
  await act(async () => first.resolve(readResult([owned])));
  expect(screen.getByTestId("routing")).toHaveTextContent("browser:activity");
  expect(api.start).not.toHaveBeenCalled();
});

it("keeps legacy activity when readiness fails despite a cached owned target", async () => {
  const owned = {
    ...environment,
    id: "22222222-2222-4222-8222-222222222222",
    state: "ready" as const,
  };
  api.items = [owned, { ...environment, kind: "desktop" }];
  vi.mocked(api.refresh).mockResolvedValue({
    ...readResult(),
    error: new Error("Controlled read refusal"),
    isError: true,
    isSuccess: false,
    isRefetchError: true,
    status: "error",
  });
  useBrowserPanelStore.getState().open("legacy-call", true);
  render(<Harness />);
  await act(async () => {});
  expect(screen.getByTestId("routing")).toHaveTextContent("browser:activity");
  expect(api.start).not.toHaveBeenCalled();
});

it.each(["failed", "expired", "not_started"] as const)(
  "does not replace legacy activity with a %s owned target",
  async (state) => {
    const owned = { ...environment, id: "22222222-2222-4222-8222-222222222222", state };
    vi.mocked(api.refresh).mockResolvedValue(readResult([owned]));
    useBrowserPanelStore.getState().open("legacy-call", true);
    render(<Harness />);
    await act(async () => {});
    expect(screen.getByTestId("routing")).toHaveTextContent("browser:activity");
    expect(api.start).not.toHaveBeenCalled();
  },
);

it("refreshes an already selected owned browser when another activity call arrives", async () => {
  vi.mocked(api.refresh).mockResolvedValue(readResult());
  useBrowserPanelStore.getState().open("first-call", true);
  render(<Harness />);
  await userEvent.click(screen.getByRole("button", { name: "Open workspace" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Browser" }));
  await act(async () => useBrowserPanelStore.getState().open("second-call", true));
  expect(api.refresh).toHaveBeenCalledTimes(2);
  expect(screen.getByTestId("routing")).toHaveTextContent("browser:browser");
  expect(api.start).not.toHaveBeenCalled();
});
