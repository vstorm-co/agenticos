import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { useLiveConversationEnvironment } from "@/hooks/use-live-conversation-environment";
import { applyBrowserFrame } from "@/lib/browse";
import type { ConversationEnvironment } from "@/lib/conversation-environments-api";
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from "@/components/ui";
import { BrowserWindow } from "./browser-window";
import { ConversationEnvironmentView } from "./conversation-environment-view";

vi.mock("@/hooks/use-live-conversation-environment", () => ({
  useLiveConversationEnvironment: vi.fn(),
}));
vi.mock("./browser-window", () => ({
  BrowserWindow: vi.fn((props: Parameters<typeof BrowserWindow>[0]) => (
    <div data-testid="environment-picture">
      {props.browse.title}
      {props.active !== false && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button>Environment options</button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>{props.menuItems}</DropdownMenuContent>
        </DropdownMenu>
      )}
      <button
        disabled={props.control === null}
        onClick={() => props.control?.send({ type: "click", x: 1, y: 2 })}
      >
        Drive screen
      </button>
    </div>
  )),
}));

const ready: ConversationEnvironment = {
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
const [picture] = applyBrowserFrame([], {
  kind: "browser_opened",
  call_id: ready.id!,
  step: 0,
  title: "Prepared page",
  url: "https://example.com",
  navigable: true,
});
let live: ReturnType<typeof useLiveConversationEnvironment>;

function props(environment: ConversationEnvironment = ready) {
  return {
    conversationId: "chat",
    environment,
    visible: true,
    onState: vi.fn().mockResolvedValue(undefined),
    onStart: vi.fn().mockResolvedValue(ready),
    onEnd: vi.fn().mockResolvedValue(undefined),
    onRefresh: vi.fn().mockResolvedValue(undefined),
    isStarting: false,
    isEnding: false,
  };
}

async function openOptions() {
  await userEvent.click(screen.getByRole("button", { name: /^(Browser|Environment) options$/ }));
}

async function openEndConfirmation() {
  await openOptions();
  await userEvent.click(screen.getByRole("menuitem", { name: "End environment" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  live = {
    status: "live",
    environment: ready,
    browse: picture!,
    tabs: null,
    selectingTab: false,
    activateTab: vi.fn(),
    send: vi.fn(),
    retry: vi.fn(),
  };
  vi.mocked(useLiveConversationEnvironment).mockImplementation(() => live);
});

it("observes a ready environment and hiding only disconnects its stream", async () => {
  const received = props();
  const view = render(<ConversationEnvironmentView {...received} />);
  const retained = screen.getByTestId("environment-picture");
  expect(retained).toHaveTextContent("Prepared page");
  await waitFor(() => expect(received.onState).toHaveBeenCalledWith(ready));
  expect(received.onStart).not.toHaveBeenCalled();
  expect(received.onEnd).not.toHaveBeenCalled();
  view.rerender(<ConversationEnvironmentView {...received} visible={false} />);
  expect(useLiveConversationEnvironment).toHaveBeenLastCalledWith("chat", ready, false);
  expect(screen.getByTestId("environment-picture")).toBe(retained);
  expect(retained).not.toBeVisible();
  view.rerender(<ConversationEnvironmentView {...received} visible />);
  expect(screen.getByTestId("environment-picture")).toBe(retained);
  expect(retained).toBeVisible();
  expect(received.onEnd).not.toHaveBeenCalled();
});

it("requires explicit confirmation before ending and supports cancelling with Escape", async () => {
  const received = props();
  render(<ConversationEnvironmentView {...received} />);
  await openEndConfirmation();
  expect(received.onEnd).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog", { name: "End this environment?" })).toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(received.onEnd).not.toHaveBeenCalled();
  await openEndConfirmation();
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "End environment" }),
  );
  await waitFor(() => expect(received.onEnd).toHaveBeenCalledOnce());
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

it("retains the confirmation on refusal without rendering transport internals", async () => {
  const received = props();
  received.onEnd.mockRejectedValue(new Error("secret-cdp-provider-handle"));
  render(<ConversationEnvironmentView {...received} />);
  await openEndConfirmation();
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "End environment" }),
  );
  await screen.findByRole("alert");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Could not end the environment");
  expect(screen.queryByText(/secret-cdp/)).not.toBeInTheDocument();
  expect(received.onStart).not.toHaveBeenCalled();
});

it("opens only on an explicit action and reports a failed start", async () => {
  const environment: ConversationEnvironment = { ...ready, id: null, state: "not_started" };
  live = { ...live, status: "connecting", environment: undefined, browse: null };
  const received = props(environment);
  received.onStart.mockRejectedValue(new Error("internal-provider-address"));
  render(<ConversationEnvironmentView {...received} />);
  expect(received.onStart).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Open environment" }));
  await screen.findByRole("alert");
  expect(received.onStart).toHaveBeenCalledOnce();
  expect(screen.getByRole("alert")).toHaveTextContent("Could not open the environment");
  expect(screen.queryByText(/internal-provider/)).not.toBeInTheDocument();
});

it.each(["capability_not_enabled", "backend_not_supported", "local_device_required"] as const)(
  "shows the controlled %s refusal without pretending Start can fix configuration",
  (code) => {
    const environment: ConversationEnvironment = {
      ...ready,
      id: null,
      state: "not_started",
      can_control: false,
      refusal: { code, message: "Configuration needs attention." },
    };
    live = { ...live, status: "connecting", environment: undefined, browse: null };
    const received = props(environment);
    render(<ConversationEnvironmentView {...received} />);
    expect(screen.getByText("Configuration needs attention.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open environment" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check availability" }));
    expect(received.onRefresh).toHaveBeenCalledOnce();
    expect(received.onStart).not.toHaveBeenCalled();
  },
);

it("starts a new expired environment explicitly without reusing its old picture", async () => {
  const environment: ConversationEnvironment = { ...ready, state: "expired" };
  live = { ...live, status: "gone", environment };
  const received = props(environment);
  render(<ConversationEnvironmentView {...received} />);
  expect(screen.queryByTestId("environment-picture")).not.toBeInTheDocument();
  await openOptions();
  expect(screen.queryByRole("menuitem", { name: "End environment" })).not.toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  await userEvent.click(screen.getByRole("button", { name: "Open new environment" }));
  expect(received.onStart).toHaveBeenCalledOnce();
});

it("reconnects a malformed stream without opening or ending a remote environment", async () => {
  live = { ...live, status: "malformed", environment: null };
  const received = props();
  render(<ConversationEnvironmentView {...received} />);
  expect(
    screen.getByRole("heading", { name: "Live view could not be verified" }),
  ).toBeInTheDocument();
  expect(screen.getByTestId("environment-picture")).not.toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Reconnect view" }));
  expect(live.retry).toHaveBeenCalledOnce();
  expect(received.onStart).not.toHaveBeenCalled();
  expect(received.onEnd).not.toHaveBeenCalled();
});

it.each(["agent", "human", "none"] as const)(
  "uses authoritative %s control without preempting the agent",
  (control) => {
    const environment: ConversationEnvironment = { ...ready, control };
    live = { ...live, environment };
    render(<ConversationEnvironmentView {...props(environment)} />);
    const drive = screen.getByRole("button", { name: "Drive screen" });
    if (control === "agent") expect(drive).toBeDisabled();
    else {
      expect(drive).toBeEnabled();
      fireEvent.click(drive);
      expect(live.send).toHaveBeenCalledWith({ type: "click", x: 1, y: 2 });
    }
  },
);

it("keeps a watch-only view noninteractive and desktop navigation unavailable", () => {
  const environment: ConversationEnvironment = { ...ready, kind: "desktop", can_control: false };
  live = { ...live, environment };
  render(<ConversationEnvironmentView {...props(environment)} />);
  expect(screen.getByRole("button", { name: "Drive screen" })).toBeDisabled();
  expect(vi.mocked(BrowserWindow).mock.lastCall?.[0].surface).toBe("desktop");
  expect(vi.mocked(BrowserWindow).mock.lastCall?.[0].browse.navigable).toBe(false);
});

it("does not offer provisioning or remote controls after access is revoked", () => {
  live = { ...live, status: "forbidden", environment: { ...ready, state: "expired" } };
  render(<ConversationEnvironmentView {...props()} />);
  expect(screen.getByRole("heading", { name: "Access unavailable" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Open new environment" })).not.toBeInTheDocument();
  expect(screen.queryByTestId("environment-picture")).not.toBeInTheDocument();
});

it("surfaces a failed state callback through controlled recovery copy", async () => {
  const received = props();
  received.onState.mockRejectedValue(new Error("internal cache failure"));
  render(<ConversationEnvironmentView {...received} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not update readiness");
});

it.each([
  ["starting", "connecting", "Preparing environment"],
  ["failed", "unavailable", "Environment unavailable"],
  ["ready", "unavailable", "Live view disconnected"],
  ["ready", "connecting", "Connecting live view"],
] as const)("shows %s / %s without presenting an old picture as live", (state, status, title) => {
  const environment: ConversationEnvironment = { ...ready, state };
  live = { ...live, status, environment };
  const received = props(environment);
  render(<ConversationEnvironmentView {...received} />);
  expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
  if (state === "ready") expect(screen.getByTestId("environment-picture")).not.toBeVisible();
  else expect(screen.queryByTestId("environment-picture")).not.toBeInTheDocument();
  expect(received.onStart).not.toHaveBeenCalled();
  expect(received.onEnd).not.toHaveBeenCalled();
});

it("does not dismiss or submit End twice while its request is pending", async () => {
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => {
    finish = resolve;
  });
  const received = props();
  received.onEnd.mockReturnValue(pending);
  render(<ConversationEnvironmentView {...received} />);
  await openEndConfirmation();
  const end = within(screen.getByRole("dialog")).getByRole("button", { name: "End environment" });
  await userEvent.click(end);
  expect(end).toBeDisabled();
  await userEvent.keyboard("{Escape}");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(received.onEnd).toHaveBeenCalledOnce();
  await act(async () => {
    finish();
    await pending;
  });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

it.each([
  {
    session_lifetime: "run" as const,
    idle_seconds: 900,
    copy: "Closes after an agent run that uses this environment",
  },
  { session_lifetime: "conversation" as const, idle_seconds: 75, copy: "75 seconds of inactivity" },
])("shows the effective $session_lifetime session policy", async (policy) => {
  const environment = {
    ...ready,
    session_lifetime: policy.session_lifetime,
    idle_seconds: policy.idle_seconds,
  };
  live = { ...live, environment };
  render(<ConversationEnvironmentView {...props(environment)} />);
  expect(screen.queryByText((text) => text.includes(policy.copy))).not.toBeInTheDocument();
  await openOptions();
  expect(screen.getByText((text) => text.includes(policy.copy))).toBeInTheDocument();
});
it("ignores a state-write failure after the view has gone away", async () => {
  let refuse!: (reason: Error) => void;
  const failed = new Promise<void>((_, reject) => {
    refuse = reject;
  });
  const received = props();
  received.onState.mockReturnValue(failed);
  const view = render(<ConversationEnvironmentView {...received} />);
  await waitFor(() => expect(received.onState).toHaveBeenCalled());
  view.unmount();
  await act(async () => {
    refuse(new Error("stale"));
    await failed.catch(() => undefined);
  });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("offers an explicit reauthorization retry without restoring expired controls", async () => {
  live = { ...live, status: "forbidden", environment: ready };
  const received = props();
  render(<ConversationEnvironmentView {...received} />);
  expect(screen.queryByTestId("environment-picture")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Reconnect view" }));
  expect(live.retry).toHaveBeenCalledOnce();
  expect(received.onStart).not.toHaveBeenCalled();
  expect(received.onEnd).not.toHaveBeenCalled();
});

it("shows a controlled failed start response even when the HTTP request succeeded", async () => {
  const environment: ConversationEnvironment = { ...ready, id: null, state: "not_started" };
  live = { ...live, status: "connecting", environment: undefined, browse: null };
  const received = props(environment);
  received.onStart.mockResolvedValue({
    ...environment,
    state: "failed",
    refusal: {
      code: "connection_unavailable",
      message: "Configure this agent’s browser connection and vault key.",
    },
  });
  render(<ConversationEnvironmentView {...received} />);
  await userEvent.click(screen.getByRole("button", { name: "Open environment" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Configure this agent’s browser connection and vault key.",
  );
  expect(received.onStart).toHaveBeenCalledOnce();
  expect(screen.queryByTestId("environment-picture")).not.toBeInTheDocument();
});

it("checks availability explicitly with busy and completed feedback without provisioning", async () => {
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => {
    finish = resolve;
  });
  const received = props();
  received.onRefresh.mockReturnValue(pending);
  render(<ConversationEnvironmentView {...received} />);
  expect(screen.queryByRole("button", { name: "Check availability" })).not.toBeInTheDocument();
  await openOptions();
  await userEvent.click(screen.getByRole("menuitem", { name: "Check availability" }));
  expect(received.onRefresh).toHaveBeenCalledOnce();
  await openOptions();
  expect(screen.getByRole("menuitem", { name: "Check availability" })).toHaveAttribute(
    "data-disabled",
  );
  await userEvent.keyboard("{Escape}");
  await act(async () => {
    finish();
    await pending;
  });
  expect(await screen.findByRole("status")).toHaveTextContent("Availability checked: Ready.");
  expect(received.onStart).not.toHaveBeenCalled();
  expect(received.onEnd).not.toHaveBeenCalled();
});

it("shows availability check failure without exposing transport details", async () => {
  const received = props();
  received.onRefresh.mockRejectedValue(new Error("secret-provider-address"));
  render(<ConversationEnvironmentView {...received} />);
  await openOptions();
  await userEvent.click(screen.getByRole("menuitem", { name: "Check availability" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not check availability");
  expect(screen.queryByText(/secret-provider-address/)).not.toBeInTheDocument();
});

it.each(["not_started", "failed", "expired"] as const)(
  "does not report a %s start response as opened without a live target",
  async (state) => {
    const environment: ConversationEnvironment = { ...ready, id: null, state: "not_started" };
    live = { ...live, status: "connecting", environment: undefined, browse: null };
    const received = props(environment);
    received.onStart.mockResolvedValue({ ...environment, state });
    render(<ConversationEnvironmentView {...received} />);
    await userEvent.click(screen.getByRole("button", { name: "Open environment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not open the environment");
    expect(screen.queryByTestId("environment-picture")).not.toBeInTheDocument();
  },
);

it("reports a completed unavailable check without creating an environment", async () => {
  const environment: ConversationEnvironment = {
    ...ready,
    id: null,
    state: "not_started",
    refusal: { code: "connection_unavailable", message: "Configure a connection first." },
  };
  live = { ...live, status: "connecting", environment: undefined, browse: null };
  const received = props(environment);
  render(<ConversationEnvironmentView {...received} />);
  await userEvent.click(screen.getByRole("button", { name: "Check availability" }));
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Availability checked: Environment unavailable.",
  );
  expect(screen.getByText("Configure a connection first.")).toBeInTheDocument();
  expect(received.onStart).not.toHaveBeenCalled();
});

it("hides and discards an unconfirmed destructive prompt when its pane is hidden", async () => {
  const received = props();
  const view = render(<ConversationEnvironmentView {...received} />);
  const picture = screen.getByTestId("environment-picture");
  await openEndConfirmation();
  expect(screen.getByRole("dialog", { name: "End this environment?" })).toBeInTheDocument();
  view.rerender(<ConversationEnvironmentView {...received} visible={false} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(received.onEnd).not.toHaveBeenCalled();
  view.rerender(<ConversationEnvironmentView {...received} visible />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByTestId("environment-picture")).toBe(picture);
});

it("dismisses a starting pane’s options portal on hide without provisioning", async () => {
  const environment: ConversationEnvironment = { ...ready, id: null, state: "not_started" };
  live = { ...live, status: "connecting", environment: undefined, browse: null };
  const received = props(environment);
  const view = render(<ConversationEnvironmentView {...received} />);
  await openOptions();
  expect(screen.getByRole("menu")).toBeInTheDocument();
  view.rerender(<ConversationEnvironmentView {...received} visible={false} />);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  view.rerender(<ConversationEnvironmentView {...received} visible />);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(received.onStart).not.toHaveBeenCalled();
});

it("retains the browser node through reconnecting while hiding the cached screen", () => {
  const received = props();
  const view = render(<ConversationEnvironmentView {...received} />);
  const picture = screen.getByTestId("environment-picture");
  live = { ...live, status: "connecting" };
  view.rerender(<ConversationEnvironmentView {...received} />);
  expect(screen.getByTestId("environment-picture")).toBe(picture);
  expect(picture).not.toBeVisible();
  expect(screen.getByRole("heading", { name: "Connecting live view" })).toBeVisible();
  expect(vi.mocked(BrowserWindow).mock.lastCall?.[0].active).toBe(false);
  live = { ...live, status: "live" };
  view.rerender(<ConversationEnvironmentView {...received} />);
  expect(screen.getByTestId("environment-picture")).toBe(picture);
  expect(picture).toBeVisible();
  expect(received.onStart).not.toHaveBeenCalled();
});

it("discards an unconfirmed End prompt when fresh authority becomes forbidden", async () => {
  const received = props();
  const view = render(<ConversationEnvironmentView {...received} />);
  await openEndConfirmation();
  expect(screen.getByRole("dialog", { name: "End this environment?" })).toBeInTheDocument();
  live = { ...live, status: "forbidden" };
  view.rerender(<ConversationEnvironmentView {...received} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(received.onEnd).not.toHaveBeenCalled();
  live = { ...live, status: "live" };
  view.rerender(<ConversationEnvironmentView {...received} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(received.onEnd).not.toHaveBeenCalled();
  expect(received.onStart).not.toHaveBeenCalled();
});
