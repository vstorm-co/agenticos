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
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => env.can }) }));
vi.mock("@/hooks/use-runs", () => ({
  useApprovals: () => ({ approvals: env.approvals, decide: env.decide }),
  useRuns: (_agent: unknown, options: unknown) => {
    env.runsQuery = options;
    return { runs: env.runs };
  },
}));
vi.mock("@/hooks/use-agents", () => ({ useAgents: () => ({ agents: env.agents }) }));
vi.mock("@/stores", () => ({
  useAuthStore: (pick: (state: unknown) => unknown) => pick({ user: { id: "u1" } }),
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
  });
  env.listeners.clear();
  vi.clearAllMocks();
  env.take.mockImplementation(async () => null);
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
    const view = mount();
    env.approvals = [];
    env.end.mockRejectedValue(new Error("no"));
    view.again();
    view.unmount();
    await waitFor(() => expect(env.report).toHaveBeenCalledTimes(4));
    expect(env.report.mock.calls.map(([what]) => what)).toEqual([
      "could not show a live activity",
      "could not end a live activity",
      "could not end a live activity",
      "could not read an activity's action",
    ]);
    env.end.mockReset();
  });
});
