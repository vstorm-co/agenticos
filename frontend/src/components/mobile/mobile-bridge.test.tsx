import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MAC_MAIN } from "@/components/desktop/fixtures";
import type { ShellInfo } from "@/lib/desktop/shell";

import { MobileBridge } from "./mobile-bridge";

const PHONE: ShellInfo = { platform: "ios", version: "0.1.0", window: "main", vibrancy: false };

const env = vi.hoisted(() => ({
  shell: null as unknown,
  can: true,
  approvals: [] as unknown[],
  runs: [] as unknown[],
  agents: [] as unknown[],
  runsQuery: undefined as unknown,
  decide: { mutate: vi.fn() },
  listeners: new Map<string, (payload: unknown) => void>(),
  push: vi.fn(),
  show: vi.fn(async (_activity: unknown) => {}),
  end: vi.fn(async (_id: string) => {}),
  take: vi.fn(async (): Promise<unknown> => null),
  report: vi.fn(),
  request: vi.fn(),
  share: vi.fn(),
  takeShared: vi.fn(async (): Promise<unknown> => null),
  warning: vi.fn(),
  loading: false,
  failed: null as unknown,
  updateWidget: vi.fn(async (_glance: unknown) => {}),
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => env.can }) }));
vi.mock("@/hooks/use-runs", () => ({
  useApprovals: () => ({
    approvals: env.approvals,
    total: env.approvals.length,
    isLoading: env.loading,
    error: env.failed,
    decide: env.decide,
  }),
  useRuns: (_agent: unknown, options: unknown) => {
    env.runsQuery = options;
    return { runs: env.runs, total: env.runs.length, isLoading: env.loading, error: null };
  },
}));
vi.mock("@/hooks/use-agents", () => ({ useAgents: () => ({ agents: env.agents }) }));
vi.mock("@/stores", () => ({
  useAuthStore: (pick: (state: unknown) => unknown) => pick({ user: { id: "u1" } }),
  useComposerIntentStore: (pick: (state: unknown) => unknown) =>
    pick({ request: env.request, share: env.share }),
}));
vi.mock("@/hooks/use-desktop", () => ({
  useShellEvent: (event: string, handler: (payload: unknown) => void) =>
    env.listeners.set(event, handler),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push: env.push }) }));
vi.mock("@/lib/mobile/live-activities", async (original) => ({
  ...(await original<typeof import("@/lib/mobile/live-activities")>()),
  showActivity: env.show,
  endActivity: env.end,
  takeActivityAction: env.take,
}));
vi.mock("@/lib/mobile/shared", () => ({ takeShared: env.takeShared }));
vi.mock("@/lib/mobile/widget", () => ({ updateWidget: env.updateWidget }));
vi.mock("sonner", () => ({ toast: { warning: env.warning } }));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  reportShellFailure: env.report,
}));

const approval = (id: string, extra = {}) => ({
  id,
  run_id: "r",
  agent_id: "a",
  agent_name: "Support",
  tool_id: "send_email",
  tool_args: { to: "a@b.c" },
  ...extra,
});
const run = (id: string, extra = {}) => ({
  id,
  agent_id: "a",
  started_at: "2026-10-21T10:00:00Z",
  ...extra,
});

beforeEach(() => {
  Object.assign(env, {
    shell: PHONE,
    can: true,
    approvals: [],
    runs: [],
    agents: [{ id: "a", name: "Support" }],
    loading: false,
    failed: null,
  });
  env.listeners.clear();
  vi.clearAllMocks();
  env.take.mockImplementation(async () => null);
  env.takeShared.mockImplementation(async () => null);
});

function mount() {
  const view = render(<MobileBridge />);
  return { ...view, again: () => view.rerender(<MobileBridge />) };
}

describe("MobileBridge", () => {
  it("does nothing in a browser or in the desktop app", () => {
    env.shell = null;
    mount().unmount();
    env.shell = MAC_MAIN;
    mount().unmount();
    expect(env.show).not.toHaveBeenCalled();
    expect(env.take).not.toHaveBeenCalled();
  });

  it("shows an approval with its buttons and the person's own running runs", () => {
    env.approvals = [approval("ap1"), approval("ap2", { agent_name: null })];
    env.runs = [run("r1"), run("r2", { agent_id: "unknown", started_at: null })];
    mount();
    expect(env.runsQuery).toMatchObject({ statuses: ["running"], userId: "u1", enabled: true });
    expect(env.show.mock.calls.map(([activity]) => activity)).toEqual([
      {
        id: "approval:ap1",
        kind: "approval",
        title: "Support wants to run send_email",
        body: "to: a@b.c",
        path: "/runs?tab=approvals",
        approvalId: "ap1",
        approveLabel: "Approve",
        rejectLabel: "Reject",
      },
      expect.objectContaining({ id: "approval:ap2", title: "An agent wants to run send_email" }),
      {
        id: "run:r1",
        kind: "run",
        title: "Support is working",
        body: "Tap to follow it in AgenticOS.",
        path: "/runs?run=r1",
        startedAt: Date.parse("2026-10-21T10:00:00Z"),
      },
      {
        id: "run:r2",
        kind: "run",
        title: "An agent is working",
        body: "Tap to follow it in AgenticOS.",
        path: "/runs?run=r2",
      },
    ]);
  });

  it("keeps the widget's counts once both are read", () => {
    env.loading = true;
    env.approvals = [approval("ap1")];
    const view = mount();
    expect(env.updateWidget).not.toHaveBeenCalled();
    env.loading = false;
    env.runs = [run("r1"), run("r2")];
    view.again();
    expect(env.updateWidget).toHaveBeenCalledWith({ approvals: 1, running: 2 });
  });

  it("leaves the widget's last counts alone when a read fails", () => {
    env.failed = new Error("500");
    mount();
    expect(env.updateWidget).not.toHaveBeenCalled();
  });

  it("keeps at most three runs live", () => {
    env.runs = ["r1", "r2", "r3", "r4"].map((id) => run(id));
    mount();
    expect(env.show).toHaveBeenCalledTimes(3);
  });

  it("redraws only what changed and ends what is over, and everything when it goes", () => {
    env.approvals = [approval("ap1")];
    env.runs = [run("r1")];
    const view = mount();
    env.show.mockClear();
    env.approvals = [approval("ap1")];
    env.runs = [run("r1"), run("r2")];
    view.again();
    expect(env.show.mock.calls.map(([activity]) => activity)).toEqual([
      expect.objectContaining({ id: "run:r2" }),
    ]);
    env.approvals = [];
    view.again();
    expect(env.end).toHaveBeenCalledWith("approval:ap1");
    env.end.mockClear();
    view.unmount();
    expect(env.end.mock.calls.map(([id]) => id).sort()).toEqual(["run:r1", "run:r2"]);
  });

  it("opens the page a tap on an activity asked for, waiting from before it mounted", async () => {
    env.take.mockImplementation(async () => ({ kind: "open", path: "/runs?run=r1" }));
    mount();
    await waitFor(() => expect(env.push).toHaveBeenCalledWith("/runs?run=r1"));
  });

  it("makes the decision a button asked for when the app says one is waiting", async () => {
    mount();
    await act(async () => {});
    env.take.mockImplementation(async () => ({
      kind: "decide",
      approval_id: "ap1",
      approved: false,
    }));
    env.listeners.get("mobile:activity")?.(null);
    await waitFor(() =>
      expect(env.decide.mutate).toHaveBeenCalledWith({ id: "ap1", approved: false }),
    );
  });

  it("opens the chat to start the call or dictation a shortcut asked for", async () => {
    env.take.mockImplementation(async () => ({ kind: "start", mode: "call" }));
    mount();
    await waitFor(() => expect(env.push).toHaveBeenCalledWith("/chat"));
    expect(env.request).toHaveBeenCalledWith("call");
  });

  it("puts what another app shared into a new message, and names what could not be attached", async () => {
    const file = new File(["hi"], "a.txt");
    env.takeShared.mockImplementation(async () => ({
      text: "look",
      files: [file],
      refused: ["big.mov"],
    }));
    mount();
    await waitFor(() => expect(env.push).toHaveBeenCalledWith("/chat"));
    expect(env.share).toHaveBeenCalledWith({ id: expect.any(Number), files: [file], text: "look" });
    expect(env.warning).toHaveBeenCalledWith("Could not attach: big.mov");
  });

  it("opens no chat when nothing shared could be attached", async () => {
    env.takeShared.mockImplementation(async () => ({ text: "", files: [], refused: ["big.mov"] }));
    mount();
    await waitFor(() => expect(env.warning).toHaveBeenCalled());
    expect(env.share).not.toHaveBeenCalled();
    expect(env.push).not.toHaveBeenCalled();
  });

  it("looks again whenever the app comes back to the front, and stops when it goes", async () => {
    const { unmount } = mount();
    await waitFor(() => expect(env.takeShared).toHaveBeenCalledOnce());
    env.takeShared.mockImplementation(async () => ({
      text: "",
      files: [new File([], "b")],
      refused: [],
    }));
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(env.takeShared).toHaveBeenCalledOnce();
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() =>
      expect(env.share).toHaveBeenCalledWith({
        id: expect.any(Number),
        files: [expect.any(File)],
        text: undefined,
      }),
    );
    unmount();
    document.dispatchEvent(new Event("visibilitychange"));
    expect(env.takeShared).toHaveBeenCalledTimes(2);
  });

  it("reads nothing a person may not, and leaves refusing a decision to the server", async () => {
    env.can = false;
    env.take.mockImplementation(async () => ({
      kind: "decide",
      approval_id: "ap1",
      approved: true,
    }));
    mount();
    await waitFor(() =>
      expect(env.decide.mutate).toHaveBeenCalledWith({ id: "ap1", approved: true }),
    );
    expect(env.runsQuery).toMatchObject({ enabled: false });
  });

  it("says where a failure to talk to the app went, rather than swallowing it", async () => {
    env.approvals = [approval("ap1")];
    env.runs = [run("r1")];
    env.show.mockRejectedValueOnce(new Error("no"));
    env.take.mockRejectedValueOnce(new Error("no"));
    env.takeShared.mockRejectedValueOnce(new Error("no"));
    env.updateWidget.mockRejectedValueOnce(new Error("no"));
    const view = mount();
    env.approvals = [];
    env.end.mockRejectedValue(new Error("no"));
    view.again();
    view.unmount();
    await waitFor(() => expect(env.report).toHaveBeenCalledTimes(6));
    expect(env.report.mock.calls.map(([what]) => what).sort()).toEqual([
      "could not end a live activity",
      "could not end a live activity",
      "could not read an activity's action",
      "could not read what was shared",
      "could not show a live activity",
      "could not update the widget",
    ]);
    env.end.mockReset();
  });
});
