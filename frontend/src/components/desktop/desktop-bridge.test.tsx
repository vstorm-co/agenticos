import { act, render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Notification } from "@/lib/notifications-api";

import { useComposerIntentStore } from "@/stores/composer-intent-store";

import { DesktopBridge } from "./desktop-bridge";
import { MAC_MAIN } from "./fixtures";

const env = vi.hoisted(() => ({
  shell: null as unknown,
  can: true,
  pending: 0,
  unread: 0,
  approvals: [] as unknown[],
  decide: { mutate: vi.fn() },
  inbox: [] as unknown[],
  listeners: new Map<string, (payload: unknown) => void>(),
  push: vi.fn(),
  notify: vi.fn(async () => {}),
  setBadge: vi.fn(async () => {}),
  report: vi.fn(),
  list: vi.fn(),
  recordApp: vi.fn(async (_shell: unknown) => {}),
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => env.can }) }));
vi.mock("@/hooks/use-assistant-signals", () => ({
  useAssistantSignals: () => ({ pendingApprovals: env.pending }),
}));
vi.mock("@/hooks/use-notifications", () => ({
  useUnreadNotificationCount: () => ({ count: env.unread }),
}));
vi.mock("@/hooks/use-runs", () => ({
  useApprovals: () => ({ approvals: env.approvals, decide: env.decide }),
}));
vi.mock("@/hooks/use-desktop", () => ({
  useShellEvent: (event: string, handler: (payload: unknown) => void) =>
    env.listeners.set(event, handler),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push: env.push }) }));
vi.mock("@/lib/notifications-api", () => ({ listNotifications: env.list }));
vi.mock("@/lib/session-app", () => ({ recordSessionApp: env.recordApp }));
vi.mock("@/lib/desktop/commands", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/commands")>()),
  notify: env.notify,
  setBadge: env.setBadge,
}));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  reportShellFailure: env.report,
}));

const approval = (id: string, extra = {}) => ({
  id,
  status: "pending",
  run_id: "r",
  agent_id: "a",
  agent_name: "Support",
  tool_id: "send_email",
  tool_args: { to: "a@b.c" },
  ...extra,
});
const row = (id: string, created_at: string, extra: Partial<Notification> = {}): Notification => ({
  id,
  event_type: "run_completed",
  summary: "Your run finished.",
  context_url: "/runs/1",
  read_at: null,
  created_at,
  ...extra,
});

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = () => (
    <QueryClientProvider client={client}>
      <DesktopBridge />
    </QueryClientProvider>
  );
  const view = render(tree());
  return { ...view, again: () => view.rerender(tree()) };
}

beforeEach(() => {
  Object.assign(env, {
    shell: MAC_MAIN,
    can: true,
    pending: 0,
    unread: 0,
    approvals: [],
    inbox: [],
  });
  env.listeners.clear();
  vi.clearAllMocks();
  env.list.mockImplementation(async () => ({ items: env.inbox, next_cursor: null }));
});

/**
 * Let the inbox page the bridge asked for arrive and be drawn. React Query
 * hands a result to its observers a macrotask after it resolves, so flushing
 * microtasks alone could leave the bridge on its first look - and the next
 * page read as one - on a loaded machine.
 */
async function inboxRead(times: number) {
  await waitFor(() => expect(env.list).toHaveBeenCalledTimes(times));
  await act(async () => {
    await env.list.mock.results[times - 1]?.value;
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

afterEach(() => {
  delete window.__agenticosNavigate;
});

describe("DesktopBridge", () => {
  it("does nothing in a browser or in another of the app's windows", () => {
    env.shell = null;
    mount().unmount();
    env.shell = { ...MAC_MAIN, window: "blobby" };
    mount().unmount();
    env.shell = { ...MAC_MAIN, platform: "ios" };
    mount();
    expect(env.setBadge).not.toHaveBeenCalled();
    expect(window.__agenticosNavigate).toBeUndefined();
  });

  it("lets the shell's menu change page in place, until it unmounts", () => {
    const { unmount } = mount();
    window.__agenticosNavigate?.("/agents");
    expect(env.push).toHaveBeenCalledWith("/agents");
    unmount();
    expect(window.__agenticosNavigate).toBeUndefined();
  });

  it("starts the call the voice call shortcut asked for, and reports anything else", () => {
    mount();
    act(() => env.listeners.get("desktop:start")?.("call"));
    expect(useComposerIntentStore.getState().intent).toBe("call");
    act(() => env.listeners.get("desktop:start")?.("dance"));
    expect(env.report).toHaveBeenCalledWith("an unknown thing to start", "dance");
    useComposerIntentStore.setState({ intent: null });
  });

  it("tells the server which app this is, and reports a refusal", async () => {
    env.recordApp.mockRejectedValueOnce(new Error("no"));
    mount();
    expect(env.recordApp).toHaveBeenCalledWith(MAC_MAIN);
    await waitFor(() =>
      expect(env.report).toHaveBeenCalledWith(
        "could not tell the server which app this is",
        expect.any(Error),
      ),
    );
  });

  it("counts what is waiting on the badge", () => {
    Object.assign(env, { pending: 2, unread: 3 });
    mount();
    expect(env.setBadge).toHaveBeenCalledWith(5);
  });

  it("notifies an approval that arrived after the first look, with buttons to decide it", () => {
    env.approvals = [approval("old")];
    const view = mount();
    expect(env.notify).not.toHaveBeenCalled();
    env.approvals = [approval("old"), approval("new"), approval("nameless", { agent_name: null })];
    view.again();
    expect(env.notify).toHaveBeenCalledWith({
      kind: "approval",
      title: "Support wants to run send_email",
      body: "to: a@b.c",
      path: "/runs?tab=approvals",
      approval_id: "new",
      approve_label: "Approve",
      reject_label: "Reject",
    });
    expect(env.notify).toHaveBeenCalledWith(
      expect.objectContaining({ title: "An agent wants to run send_email" }),
    );
  });

  it("watches no queue for somebody who may not decide", () => {
    env.can = false;
    env.approvals = [approval("a")];
    const view = mount();
    env.approvals = [approval("a"), approval("b")];
    view.again();
    expect(env.notify).not.toHaveBeenCalled();
  });

  it("notifies an inbox row that arrived after the first look", async () => {
    env.inbox = [row("1", "2026-10-21T10:00:00Z")];
    const view = mount();
    await inboxRead(1);
    env.inbox = [
      row("2", "2026-10-21T10:05:00Z", {
        agent: { id: "a", slug: "s", name: "Support", has_avatar: false, avatar_color: null },
      }),
      row("3", "2026-10-21T10:06:00Z", { context_url: null }),
      ...env.inbox,
    ];
    env.unread = 2;
    view.again();
    await waitFor(() => expect(env.notify).toHaveBeenCalledTimes(2));
    expect(env.notify).toHaveBeenCalledWith({
      kind: "inbox",
      title: "Support",
      body: "Your run finished.",
      path: "/runs/1",
    });
    expect(env.notify).toHaveBeenCalledWith({
      kind: "inbox",
      title: "AgenticOS",
      body: "Your run finished.",
      path: "/dashboard",
    });
  });

  it("decides an approval from its notification, and ignores a decision it cannot read", () => {
    mount();
    act(() => env.listeners.get("desktop:approval")?.({ approval_id: "ap1", approved: true }));
    expect(env.decide.mutate).toHaveBeenCalledWith({ id: "ap1", approved: true });
    act(() => env.listeners.get("desktop:approval")?.({ approval_id: 1 }));
    expect(env.report).toHaveBeenCalled();
  });

  it("reports a badge or a notification the shell refused", async () => {
    env.setBadge.mockRejectedValueOnce(new Error("refused"));
    env.notify.mockRejectedValue(new Error("refused"));
    env.approvals = [];
    env.inbox = [];
    const view = mount();
    await waitFor(() =>
      expect(env.report).toHaveBeenCalledWith("could not set the badge", expect.any(Error)),
    );
    await inboxRead(1);
    env.approvals = [approval("x")];
    env.inbox = [row("9", "2026-10-21T11:00:00Z")];
    env.unread = 1;
    view.again();
    await waitFor(() =>
      expect(env.report).toHaveBeenCalledWith("could not notify an approval", expect.any(Error)),
    );
    await waitFor(() =>
      expect(env.report).toHaveBeenCalledWith("could not notify", expect.any(Error)),
    );
  });
});
