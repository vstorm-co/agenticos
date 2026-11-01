import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { DesktopActivityBridge } from "./desktop-activity-bridge";
import { useAuthStore, useConversationStore } from "@/stores";
import { useWorkingStore } from "@/stores/working-store";
import { useDesktopLiveStore } from "@/stores/desktop-live-store";
const env = vi.hoisted(() => ({
  path: "/chat",
  publish: vi.fn().mockResolvedValue(undefined),
  report: vi.fn(),
  runs: [
    {
      id: "r",
      user_id: "me",
      agent_id: "a",
      conversation_id: "c" as string | null,
      status: "running",
    },
  ],
  approvals: [{ id: "p", status: "pending", agent_name: null as string | null }],
  agents: [{ id: "a", name: "Agent" }],
}));
vi.mock("next/navigation", () => ({ usePathname: () => env.path }));
vi.mock("@/hooks/use-desktop-active-runs", () => ({
  useDesktopActiveRuns: () => ({ runs: env.runs }),
}));
vi.mock("@/hooks/use-organizations", () => ({ useTenantId: () => "org" }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));
vi.mock("@/hooks/use-agents", () => ({ useAgents: () => ({ agents: env.agents }) }));
vi.mock("@/hooks/use-runs", () => ({ useApprovals: () => ({ approvals: env.approvals }) }));
vi.mock("@/lib/desktop/readiness", () => ({ publishDesktopActivity: env.publish }));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  reportShellFailure: env.report,
}));
beforeEach(() => {
  vi.clearAllMocks();
  env.publish.mockResolvedValue(undefined);
  useAuthStore.setState({
    user: { id: "me", email: "me@example.test", is_active: true, created_at: "now" },
  });
  useConversationStore.setState({ currentConversationId: "c" });
  useWorkingStore.setState({ since: { c: "now" }, handedOff: {} });
  useDesktopLiveStore.setState({ turns: {} });
});
it("publishes only this user's runs and pending approvals, with stop available only for owned turns", async () => {
  env.runs = [
    { id: "r", user_id: "me", agent_id: "a", conversation_id: "c", status: "running" },
    { id: "r2", user_id: "other", agent_id: "a", conversation_id: null, status: "running" },
  ];
  env.approvals = [
    { id: "p", status: "pending", agent_name: "Named" },
    { id: "done", status: "approved", agent_name: null },
  ];
  const view = render(<DesktopActivityBridge />);
  await waitFor(() =>
    expect(env.publish).toHaveBeenCalledWith(
      [
        expect.objectContaining({ id: "c", stop_conversation: "c", path: "/chat?id=c" }),
        expect.objectContaining({ id: "p", stop_conversation: null }),
      ],
      "c",
      { user: "me", organization: "org" },
    ),
  );
  act(() => {
    useWorkingStore.setState({ handedOff: { c: true } });
    useDesktopLiveStore.setState({
      turns: {
        c: { conversation: "c", state: "question", canStop: false },
        new: { conversation: "new", state: "approval", canStop: true },
      },
    });
  });
  await waitFor(() =>
    expect(env.publish).toHaveBeenLastCalledWith(
      expect.arrayContaining([
        expect.objectContaining({ id: "c", question: true, stop_conversation: null }),
        expect.objectContaining({ id: "new", stop_conversation: "new" }),
      ]),
      "c",
      expect.anything(),
    ),
  );
  env.path = "/runs";
  env.agents = [];
  env.runs = [
    {
      id: "q",
      user_id: "me",
      agent_id: "missing",
      conversation_id: null,
      status: "awaiting_answer",
    },
    {
      id: "a",
      user_id: "me",
      agent_id: "missing",
      conversation_id: "a",
      status: "awaiting_approval",
    },
  ];
  env.approvals = [{ id: "p", status: "pending", agent_name: null }];
  view.rerender(<DesktopActivityBridge />);
  await waitFor(() =>
    expect(env.publish).toHaveBeenLastCalledWith(
      expect.arrayContaining([
        expect.objectContaining({ id: "q", path: "/runs/q" }),
        expect.objectContaining({ id: "a" }),
      ]),
      null,
      expect.anything(),
    ),
  );
  env.publish.mockRejectedValue(new Error("offline"));
  view.unmount();
  await waitFor(() =>
    expect(env.report).toHaveBeenCalledWith("clearing desktop activity", expect.any(Error)),
  );
});
it("reports publication errors and preserves a run's stop action when live state cannot stop", async () => {
  env.path = "/chat";
  env.runs = [{ id: "r", user_id: "me", agent_id: "a", conversation_id: "c", status: "running" }];
  env.approvals = [];
  useDesktopLiveStore.setState({
    turns: { c: { conversation: "c", state: "running", canStop: false } },
  });
  env.publish.mockRejectedValueOnce(new Error("offline"));
  render(<DesktopActivityBridge />);
  await waitFor(() =>
    expect(env.report).toHaveBeenCalledWith("publishing desktop activity", expect.any(Error)),
  );
  expect(env.publish.mock.calls[0]?.[0]).toEqual([
    expect.objectContaining({ stop_conversation: "c", question: false }),
  ]);
});
