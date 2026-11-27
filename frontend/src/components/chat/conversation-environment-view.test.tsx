import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { useLiveConversationEnvironment } from "@/hooks/use-live-conversation-environment";
import { applyBrowserFrame } from "@/lib/browse";
import type { ConversationEnvironment } from "@/lib/conversation-environments-api";
import { BrowserWindow } from "./browser-window";
import { ConversationEnvironmentView } from "./conversation-environment-view";

vi.mock("@/hooks/use-live-conversation-environment", () => ({
  useLiveConversationEnvironment: vi.fn(),
}));
vi.mock("./browser-window", () => ({
  BrowserWindow: vi.fn((props: Parameters<typeof BrowserWindow>[0]) => (
    <div data-testid="environment-picture">
      {props.browse.title}
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
    onStart: vi.fn().mockResolvedValue(undefined),
    onEnd: vi.fn().mockResolvedValue(undefined),
    onRefresh: vi.fn(),
    isStarting: false,
    isEnding: false,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  live = { status: "live", environment: ready, browse: picture!, send: vi.fn(), retry: vi.fn() };
  vi.mocked(useLiveConversationEnvironment).mockImplementation(() => live);
});

it("observes a ready environment and hiding only disconnects its stream", async () => {
  const received = props();
  const view = render(<ConversationEnvironmentView {...received} />);
  expect(screen.getByTestId("environment-picture")).toHaveTextContent("Prepared page");
  await waitFor(() => expect(received.onState).toHaveBeenCalledWith(ready));
  expect(received.onStart).not.toHaveBeenCalled();
  expect(received.onEnd).not.toHaveBeenCalled();
  view.rerender(<ConversationEnvironmentView {...received} visible={false} />);
  expect(useLiveConversationEnvironment).toHaveBeenLastCalledWith("chat", ready, false);
  expect(screen.queryByTestId("environment-picture")).not.toBeInTheDocument();
  expect(received.onEnd).not.toHaveBeenCalled();
});

it("requires explicit confirmation before ending and supports cancelling with Escape", async () => {
  const received = props();
  render(<ConversationEnvironmentView {...received} />);
  await userEvent.click(screen.getByRole("button", { name: "End environment" }));
  expect(received.onEnd).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog", { name: "End this environment?" })).toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(received.onEnd).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "End environment" }));
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
  await userEvent.click(screen.getByRole("button", { name: "End environment" }));
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
  expect(screen.queryByRole("button", { name: "End environment" })).not.toBeInTheDocument();
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
  expect(screen.queryByTestId("environment-picture")).not.toBeInTheDocument();
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
  expect(screen.queryByTestId("environment-picture")).not.toBeInTheDocument();
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
  await userEvent.click(screen.getByRole("button", { name: "End environment" }));
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
])("shows the effective $session_lifetime session policy", (policy) => {
  const environment = {
    ...ready,
    session_lifetime: policy.session_lifetime,
    idle_seconds: policy.idle_seconds,
  };
  live = { ...live, environment };
  render(<ConversationEnvironmentView {...props(environment)} />);
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
