import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ActionConsentsDialog } from "./action-consents-dialog";
import type { RoutineToolOptions } from "@/lib/routine-tools-api";
import type { Trigger } from "@/types/triggers";

vi.mock("./source-consents-panel", () => ({
  SourceConsentsPanel: ({ onModeChange }: { onModeChange: (mode: "follow_agent") => void }) => (
    <button onClick={() => onModeChange("follow_agent")}>Follow source settings</button>
  ),
}));
const state = vi.hoisted(() => ({
  data: undefined as RoutineToolOptions | undefined,
  error: null as Error | null,
  loading: false,
  pending: false,
  save: vi.fn(),
  sourcesSave: vi.fn(),
  retry: vi.fn(),
  sourceCurrent: true,
  sourceMode: "restricted" as "restricted" | "follow_agent" | undefined,
  sourceError: null as Error | null,
  sourceLoading: false,
  sourceUnavailable: [] as string[],
  sourceData: true,
}));
vi.mock("@/hooks/use-routine-tools", () => ({
  useRoutineTools: () => ({
    data: state.data,
    error: state.error,
    isLoading: state.loading,
    replace: { mutateAsync: state.save, isPending: state.pending },
    refetch: state.retry,
  }),
}));
vi.mock("@/hooks/use-routine-sources", () => ({
  useRoutineSources: () => ({
    data: state.sourceData
      ? {
          current: state.sourceCurrent,
          mode: state.sourceMode,
          review_token: "source-review",
          unavailable_sources: state.sourceUnavailable,
          required_unavailable_sources: state.sourceUnavailable,
        }
      : undefined,
    error: state.sourceError,
    isLoading: state.sourceLoading,
    replace: { mutateAsync: state.sourcesSave, isPending: false },
  }),
}));
const trigger: Trigger = {
  id: "routine",
  agent_id: "agent",
  agent_name: "Analyst",
  name: "Daily report",
  created_by_user_id: "owner",
  is_active: true,
  can_manage: true,
  environment_id: null,
  runs_as_creator: true,
  action_mode: "agent",
  trigger_type: "schedule",
  schedule_kind: "interval",
  interval_seconds: 900,
  cron_expression: null,
  time_zone: null,
  overlap: "skip",
  event_source: null,
  event_config: {},
  prompt: "Prepare report",
  next_fire_at: null,
  last_fired_at: null,
  last_run_id: null,
  conversation_id: null,
  webhook_url: null,
  created_at: null,
  updated_at: null,
};
function options(): RoutineToolOptions {
  return {
    unavailable_settings: [],
    unavailable_sources: [],
    items: [
      {
        capability_id: "sandbox",
        capability_name: "Sandbox",
        tool_id: "read",
        name: "Read a file",
        effect: false,
        agent: "free",
        setting: null,
      },
      {
        capability_id: "sandbox",
        capability_name: "Sandbox",
        tool_id: "delete",
        name: "Delete a file",
        effect: true,
        agent: "ask",
        setting: null,
      },
      {
        connection_id: "account-a",
        account_name: "Work",
        account_scope: "personal",
        tool_id: "send",
        name: "Send mail",
        effect: true,
        agent: "ask",
        setting: null,
      },
      {
        connection_id: "account-b",
        account_name: "Team",
        account_scope: "organization",
        tool_id: "send",
        name: "Send mail",
        effect: true,
        agent: "free",
        setting: "off",
      },
      {
        kind: "platform",
        group: "tasks",
        tool_id: "task",
        name: "Create task",
        effect: true,
        agent: "free",
        setting: null,
      },
    ],
  };
}
beforeEach(() => {
  vi.clearAllMocks();
  state.data = options();
  state.error = null;
  state.loading = false;
  state.pending = false;
  state.sourceCurrent = true;
  state.sourceMode = "restricted";
  state.sourceError = null;
  state.sourceLoading = false;
  state.sourceUnavailable = [];
  state.sourceData = true;
  state.save.mockResolvedValue(options());
  state.sourcesSave.mockResolvedValue(undefined);
});

it("shows agent-required gates and offers only follow, ask or off", async () => {
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getAllByText("Agent requires approval")).toHaveLength(2);
  await userEvent.click(screen.getByRole("combobox", { name: /Delete a file/ }));
  expect(screen.getByRole("option", { name: "Follow agent" })).toBeVisible();
  expect(screen.getByRole("option", { name: "Off" })).toBeVisible();
  expect(screen.queryByRole("option", { name: "Ask every time" })).toBeNull();
  expect(screen.queryByText("Approve everything")).toBeNull();
});
it("saves exact keys for same-named account tools and only chosen restrictions", async () => {
  const close = vi.fn();
  render(<ActionConsentsDialog trigger={trigger} onClose={close} />);
  await userEvent.click(screen.getByRole("combobox", { name: /Read a file/ }));
  await userEvent.click(screen.getByRole("option", { name: "Ask every time" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(state.save).toHaveBeenCalledWith([
    { capability_id: "sandbox", tool_id: "read", setting: "ask" },
    { connection_id: "account-b", tool_id: "send", setting: "off" },
  ]);
  expect(state.sourcesSave).not.toHaveBeenCalled();
  await waitFor(() => expect(close).toHaveBeenCalled());
});
it("resets to agent rules without weakening an agent's required approval", async () => {
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Follow agent for all tools" }));
  expect(screen.getAllByText("Agent requires approval")).toHaveLength(2);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(state.save).toHaveBeenCalledWith([]);
});
it("warns before replacing legacy standing approvals", () => {
  render(
    <ActionConsentsDialog trigger={{ ...trigger, action_mode: "per_tool" }} onClose={vi.fn()} />,
  );
  expect(screen.getByText(/removes this routine’s previous standing approvals/)).toBeVisible();
});
it("searches tool names and account groups, and reports no matches", async () => {
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  await userEvent.type(screen.getByRole("searchbox", { name: "Find a tool" }), "Team");
  expect(screen.getAllByRole("combobox")).toHaveLength(1);
  expect(screen.getByText("Organization account · Team")).toBeVisible();
  await userEvent.clear(screen.getByRole("searchbox"));
  await userEvent.type(screen.getByRole("searchbox"), "missing");
  expect(screen.getByText("No tools match this search.")).toBeVisible();
});
it("explains an empty catalog and unavailable connections", () => {
  state.data = { items: [], unavailable_settings: [], unavailable_sources: ["Notion"] };
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByText("This routine has no configurable tools.")).toBeVisible();
  expect(screen.getByText("Check these connections to see their tools: Notion.")).toBeVisible();
});
it("reports a refused tool fetch, retries and cannot save cached options as success", async () => {
  state.error = new Error("denied");
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(state.retry).toHaveBeenCalled();
});
it("cannot save while tools are loading or absent", () => {
  state.loading = true;
  state.data = undefined;
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});
it.each(["error", "loading", "missing", "unavailable"] as const)(
  "blocks enabling when source review is %s",
  (kind) => {
    if (kind === "error") state.sourceError = new Error("source denied");
    if (kind === "loading") state.sourceLoading = true;
    if (kind === "missing") state.sourceData = false;
    if (kind === "unavailable") state.sourceUnavailable = ["Mail"];
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Enable routine" })).toBeDisabled();
  },
);
it("saves sources before restrictions and enables only after both succeed", async () => {
  const close = vi.fn();
  const enable = vi.fn();
  render(<ActionConsentsDialog trigger={trigger} onClose={close} onSaved={enable} />);
  await userEvent.click(screen.getByRole("button", { name: "Follow source settings" }));
  await userEvent.click(screen.getByRole("button", { name: "Enable routine" }));
  expect(state.sourcesSave).toHaveBeenCalledWith({
    review_token: "source-review",
    mode: "follow_agent",
  });
  await waitFor(() => expect(enable).toHaveBeenCalled());
  expect(close).toHaveBeenCalled();
  expect(state.sourcesSave.mock.invocationCallOrder[0]).toBeLessThan(
    state.save.mock.invocationCallOrder[0] ?? 0,
  );
});
it("keeps the dialog open after a rejected save and permits correction", async () => {
  const close = vi.fn();
  state.save.mockRejectedValueOnce(new Error("Permission changed"));
  render(<ActionConsentsDialog trigger={trigger} onClose={close} />);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(state.save).toHaveBeenCalled());
  expect(close).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(close).toHaveBeenCalled();
});
it("drops local edits when a new catalog replaces the displayed version", async () => {
  const view = render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  await userEvent.click(screen.getByRole("combobox", { name: /Read a file/ }));
  await userEvent.click(screen.getByRole("option", { name: "Off" }));
  state.data = { ...options(), items: [] };
  view.rerender(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(state.save).toHaveBeenCalledWith([]);
});
it("can postpone setup without saving and disables every control while pending", async () => {
  const close = vi.fn();
  const view = render(<ActionConsentsDialog trigger={trigger} onClose={close} onSaved={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Finish later" }));
  expect(close).toHaveBeenCalled();
  state.pending = true;
  view.rerender(<ActionConsentsDialog trigger={trigger} onClose={close} onSaved={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Finish later" })).toBeDisabled();
  for (const control of screen.getAllByRole("combobox")) expect(control).toBeDisabled();
});

it("keeps unavailable restrictions during another edit, and removes them only explicitly", async () => {
  state.data = {
    ...options(),
    unavailable_settings: [{ connection_id: "missing", tool_id: "write_notes", setting: "off" }],
  };
  const view = render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByText("Unavailable tool restrictions")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(state.save).toHaveBeenLastCalledWith(
    expect.arrayContaining([{ connection_id: "missing", tool_id: "write_notes", setting: "off" }]),
  );
  await userEvent.click(screen.getByRole("button", { name: /Remove restriction for write_notes/ }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(state.save).toHaveBeenLastCalledWith([
    { connection_id: "account-b", tool_id: "send", setting: "off" },
  ]);
  view.unmount();
});

it("can follow the agent again for one tool and save refreshed source consent", async () => {
  state.sourceMode = undefined;
  state.sourceCurrent = false;
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  const controls = screen.getAllByRole("combobox", { name: /Send mail/ });
  await userEvent.click(controls[1]!);
  await userEvent.click(screen.getByRole("option", { name: "Follow agent" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(state.save).toHaveBeenCalledWith([]);
  expect(state.sourcesSave).toHaveBeenCalledWith({
    review_token: "source-review",
    mode: "restricted",
  });
});
it("dismisses with Escape but keeps an in-flight save open", async () => {
  const close = vi.fn();
  const view = render(<ActionConsentsDialog trigger={trigger} onClose={close} />);
  await userEvent.keyboard("{Escape}");
  expect(close).toHaveBeenCalled();
  close.mockClear();
  state.pending = true;
  view.rerender(<ActionConsentsDialog trigger={trigger} onClose={close} />);
  await userEvent.keyboard("{Escape}");
  expect(close).not.toHaveBeenCalled();
});
