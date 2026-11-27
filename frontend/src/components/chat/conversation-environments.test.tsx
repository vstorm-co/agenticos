import { useEffect, useState, type ComponentProps } from "react";
import type { ConversationEnvironmentView } from "./conversation-environment-view";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useConversationEnvironments } from "@/hooks/use-conversation-environments";
import type { ConversationEnvironment } from "@/lib/conversation-environments-api";
import { applyBrowserFrame, type Browse } from "@/lib/browse";
import {
  ChatWorkspaceProvider,
  useRequiredChatWorkspace,
  type WorkspaceEnvironment,
} from "./chat-workspace-context";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";
import { ConversationEnvironments } from "./conversation-environments";

vi.mock("@/hooks/use-conversation-environments", () => ({ useConversationEnvironments: vi.fn() }));
const lifetime = vi.hoisted(() => ({
  mounts: [] as string[],
  unmounts: [] as string[],
  errors: [] as unknown[],
}));
vi.mock("./conversation-environment-view", () => ({
  ConversationEnvironmentView: ({
    visible,
    onStart,
    onEnd,
    onState,
    onRefresh,
    environment: current,
  }: ComponentProps<typeof ConversationEnvironmentView>) => {
    useEffect(() => {
      lifetime.mounts.push(current.kind);
      return () => {
        lifetime.unmounts.push(current.kind);
      };
    }, [current.kind]);
    return visible ? (
      <>
        <div data-testid="environment-target">{current.id}</div>
        <button onClick={() => void onStart()}>Prepare test environment</button>
        <button onClick={() => void onEnd()}>End test environment</button>
        <button onClick={() => void onState(current)}>Receive test state</button>
        <button
          onClick={() =>
            void Promise.resolve()
              .then(onRefresh)
              .catch((error: unknown) => lifetime.errors.push(error))
          }
        >
          Refresh test state
        </button>
      </>
    ) : null;
  },
}));
const agent = "11111111-1111-4111-8111-111111111111";
const panels = ["browser", "desktop"] as const;
const ownedId = "22222222-2222-4222-8222-222222222222";
function activity(callId: string, environmentId: string | null = ownedId): Browse[] {
  return applyBrowserFrame([], {
    kind: "browser_opened",
    call_id: callId,
    step: 0,
    environment_id: environmentId,
    navigable: true,
  });
}
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
  availablePanels = panels,
  browses = [],
}: {
  conversation?: string | null;
  preparing?: boolean;
  availablePanels?: readonly WorkspaceEnvironment[];
  browses?: Browse[];
}) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  return (
    <ChatWorkspaceProvider shared conversationId={conversation} environmentPanels={availablePanels}>
      <div ref={setSlot} />
      <RoutingControls />
      <ConversationEnvironments
        conversationId={conversation}
        agentId={agent}
        panels={availablePanels}
        browses={browses}
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
  useSourcesPanelStore.setState({ isOpen: false });
  lifetime.errors = [];
  lifetime.mounts = [];
  lifetime.unmounts = [];
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

function readResult(items = api.items ?? []): NonNullable<Awaited<ReturnType<typeof api.refresh>>> {
  return { data: { items }, error: null };
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
    render(<Harness browses={activity("owned-call")} />);
    expect(screen.getByTestId("routing")).toHaveTextContent("browser:activity");
    await act(async () => answer.resolve(readResult()));
    expect(screen.getByTestId("routing")).toHaveTextContent("browser:browser");
    expect(screen.getByTestId("environment-target")).toHaveTextContent(owned.id);
    expect(api.start).not.toHaveBeenCalled();
    expect(prepare).not.toHaveBeenCalled();
    expect(api.refresh).toHaveBeenCalledOnce();
  },
);

it.each([null, "33333333-3333-4333-8333-333333333333"])(
  "keeps an independent delegate browser when its environment is %s",
  async (environmentId) => {
    const owned = { ...environment, id: ownedId, state: "ready" as const };
    api.items = [owned, { ...environment, kind: "desktop" }];
    vi.mocked(api.refresh).mockResolvedValue(readResult());
    useBrowserPanelStore.getState().open("delegate-call", true);
    render(<Harness browses={activity("delegate-call", environmentId)} />);
    await waitFor(() => expect(api.refresh).toHaveBeenCalledOnce());
    expect(screen.getByTestId("routing")).toHaveTextContent("browser:activity");
    expect(api.start).not.toHaveBeenCalled();
    expect(prepare).not.toHaveBeenCalled();
  },
);

it("requires a fresh read when an activity acquires its actual environment identity", async () => {
  const owned = { ...environment, id: ownedId, state: "ready" as const };
  api.items = [owned, { ...environment, kind: "desktop" }];
  vi.mocked(api.refresh).mockResolvedValue(readResult());
  useBrowserPanelStore.getState().open("owned-call", true);
  const view = render(<Harness browses={activity("owned-call", null)} />);
  await waitFor(() => expect(api.refresh).toHaveBeenCalledOnce());
  expect(screen.getByTestId("routing")).toHaveTextContent("browser:activity");
  view.rerender(<Harness browses={activity("owned-call")} />);
  await waitFor(() => expect(api.refresh).toHaveBeenCalledTimes(2));
  expect(screen.getByTestId("routing")).toHaveTextContent("browser:browser");
  expect(api.start).not.toHaveBeenCalled();
});

it.each(["Desktop tab", "Show visual"])(
  "does not preempt %s when an old readiness read completes",
  async (control) => {
    const answer = Promise.withResolvers<Awaited<ReturnType<typeof api.refresh>>>();
    vi.mocked(api.refresh).mockReturnValue(answer.promise);
    useBrowserPanelStore.getState().open("owned-call", true);
    render(<Harness browses={activity("owned-call")} />);
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
  render(<Harness browses={activity("first-call")} />);
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
  });
  useBrowserPanelStore.getState().open("legacy-call", true);
  render(<Harness browses={activity("legacy-call")} />);
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
    render(<Harness browses={activity("legacy-call")} />);
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

it("keeps legacy activity when the refresh was cancelled by a scope change", async () => {
  vi.mocked(api.refresh).mockResolvedValue(null);
  useBrowserPanelStore.getState().open("legacy-call", true);
  render(<Harness />);
  await act(async () => {});
  expect(screen.getByTestId("routing")).toHaveTextContent("browser:activity");
  expect(api.start).not.toHaveBeenCalled();
});

it("falls back to legacy activity when the selected agent no longer offers the remembered browser", async () => {
  vi.mocked(api.refresh).mockResolvedValue(readResult());
  useBrowserPanelStore.getState().open("legacy-call", true);
  const view = render(<Harness />);
  await userEvent.click(screen.getByRole("button", { name: "Open workspace" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Browser" }));
  expect(screen.getByTestId("routing")).toHaveTextContent("browser:browser");
  view.rerender(<Harness availablePanels={[]} />);
  await userEvent.click(screen.getByRole("button", { name: "Browser tab" }));
  expect(screen.getByTestId("routing")).toHaveTextContent("browser:activity");
  expect(
    screen.queryByRole("button", { name: "Prepare test environment" }),
  ).not.toBeInTheDocument();
  expect(api.start).not.toHaveBeenCalled();
});

it("retains the same owned view mounts across tab changes and the next message", async () => {
  const desktop = {
    ...environment,
    kind: "desktop" as const,
    id: ownedId,
    state: "ready" as const,
  };
  api.items = [environment, desktop];
  const frames = activity("desktop-call").map((entry) => ({ ...entry, navigable: false }));
  vi.mocked(api.refresh).mockResolvedValue(readResult());
  const view = render(<Harness browses={frames} />);
  await waitFor(() => expect(screen.getByTestId("routing")).toHaveTextContent("desktop:desktop"));
  expect(lifetime.mounts).toEqual(["browser", "desktop"]);
  view.rerender(<Harness browses={[]} />);
  expect(screen.getByTestId("routing")).toHaveTextContent("desktop:desktop");
  await userEvent.click(screen.getByRole("button", { name: "Browser tab" }));
  await userEvent.click(screen.getByRole("button", { name: "Desktop tab" }));
  expect(lifetime.mounts).toEqual(["browser", "desktop"]);
  expect(lifetime.unmounts).toEqual([]);
  expect(api.start).not.toHaveBeenCalled();
});

it("does not replace a reader's selection while desktop authority is being checked", async () => {
  const answer = Promise.withResolvers<Awaited<ReturnType<typeof api.refresh>>>();
  vi.mocked(api.refresh).mockReturnValue(answer.promise);
  const frames = activity("desktop-call").map((entry) => ({ ...entry, navigable: false }));
  render(<Harness browses={frames} />);
  await userEvent.click(screen.getByRole("button", { name: "Show visual" }));
  await act(async () =>
    answer.resolve(readResult([{ ...environment, kind: "desktop", id: ownedId, state: "ready" }])),
  );
  expect(screen.getByTestId("routing")).toHaveTextContent("visuals:activity");
  expect(api.start).not.toHaveBeenCalled();
});

it("refuses an unrelated desktop environment identity", async () => {
  vi.mocked(api.refresh).mockResolvedValue(
    readResult([{ ...environment, kind: "desktop", id: "foreign", state: "ready" }]),
  );
  const frames = activity("desktop-call").map((entry) => ({ ...entry, navigable: false }));
  render(<Harness browses={frames} />);
  await act(async () => {});
  expect(screen.getByTestId("routing")).toHaveTextContent(":activity");
  expect(api.start).not.toHaveBeenCalled();
});

it.each(["failed", "expired", "not_started"] as const)(
  "does not auto-open a %s desktop",
  async (state) => {
    vi.mocked(api.refresh).mockResolvedValue(
      readResult([{ ...environment, kind: "desktop", id: ownedId, state }]),
    );
    render(
      <Harness
        browses={activity("desktop-call").map((entry) => ({ ...entry, navigable: false }))}
      />,
    );
    await act(async () => {});
    expect(screen.getByTestId("routing")).toHaveTextContent(":activity");
  },
);

it("does not reopen a dismissed desktop on the next tool action in the same environment", async () => {
  const owned = { ...environment, kind: "desktop" as const, id: ownedId, state: "ready" as const };
  api.items = [environment, owned];
  vi.mocked(api.refresh).mockResolvedValue(readResult());
  const frames = (id: string) => activity(id).map((entry) => ({ ...entry, navigable: false }));
  const view = render(<Harness browses={frames("first")} />);
  await waitFor(() => expect(screen.getByTestId("routing")).toHaveTextContent("desktop:desktop"));
  await userEvent.click(screen.getByRole("button", { name: "Close workspace" }));
  view.rerender(<Harness browses={frames("second")} />);
  await act(async () => {});
  expect(screen.getByTestId("routing")).toHaveTextContent(":desktop");
  expect(api.refresh).toHaveBeenCalledOnce();
});

it("propagates an explicit refresh refusal to the view rather than reporting success", async () => {
  const error = new Error("Controlled refresh refusal");
  vi.mocked(api.refresh).mockResolvedValue({ data: undefined, error });
  render(<Harness />);
  await userEvent.click(screen.getByRole("button", { name: "Open workspace" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Browser" }));
  await userEvent.click(screen.getByRole("button", { name: "Refresh test state" }));
  await waitFor(() => expect(lifetime.errors).toEqual([error]));
});

it("keeps sources open when a desktop becomes ready in the background", async () => {
  const answer = Promise.withResolvers<Awaited<ReturnType<typeof api.refresh>>>();
  vi.mocked(api.refresh).mockReturnValue(answer.promise);
  const frames = activity("desktop-call").map((entry) => ({ ...entry, navigable: false }));
  render(<Harness browses={frames} />);
  await act(async () => useSourcesPanelStore.setState({ isOpen: true }));
  await act(async () =>
    answer.resolve(readResult([{ ...environment, kind: "desktop", id: ownedId, state: "ready" }])),
  );
  expect(useSourcesPanelStore.getState().isOpen).toBe(true);
  expect(screen.getByTestId("routing")).toHaveTextContent(":activity");
  expect(api.start).not.toHaveBeenCalled();
});
