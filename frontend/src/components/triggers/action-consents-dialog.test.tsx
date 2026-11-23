import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useOrgStore } from "@/stores";
import { ActionConsentsDialog } from "./action-consents-dialog";
import type { RoutineActionOptions } from "@/lib/routine-actions-api";
import type { Trigger } from "@/types/triggers";

vi.mock("./source-consents-panel", () => ({
  SourceConsentsPanel: ({
    onModeChange,
  }: {
    onModeChange: (mode: "follow_agent" | "restricted") => void;
  }) => <button onClick={() => onModeChange("follow_agent")}>Follow source settings</button>,
}));
vi.mock("@/components/branding/branding-provider", () => ({
  useBranding: () => ({ appName: "AgenticOS", logoUrl: null }),
}));

const state = vi.hoisted(() => ({
  data: {
    can_waive: true,
    waive_blocked_reason: null as "permission" | "organization" | null,
    review_token: "review-1",
    items: [
      {
        capability_id: "sandbox",
        tool_id: "execute",
        name: "execute",
        consented: false,
        waivable: true,
      },
      {
        capability_id: "other",
        tool_id: "publish",
        name: "publish",
        consented: false,
        waivable: false,
      },
    ],
  } as RoutineActionOptions,
  error: null as Error | null,
  loading: false,
  save: vi.fn(),
  sourcesSave: vi.fn(),
  sourceCurrent: true,
  sourceMode: undefined as "follow_agent" | "restricted" | undefined,
  sourceError: null as Error | null,
  sourceUnavailable: [] as string[],
  requiredUnavailable: [] as string[] | undefined,
  retry: vi.fn(),
}));
vi.mock("@/hooks/use-routine-actions", () => ({
  useRoutineActions: () => ({
    data: state.data,
    isLoading: state.loading,
    error: state.error,
    replace: { mutate: state.save, mutateAsync: state.save, isPending: false },
    refetch: state.retry,
  }),
}));
vi.mock("@/hooks/use-routine-sources", () => ({
  useRoutineSources: () => ({
    data: {
      current: state.sourceCurrent,
      mode: state.sourceMode,
      review_token: "source-review",
      unavailable_sources: state.sourceUnavailable,
      required_unavailable_sources: state.requiredUnavailable,
    },
    error: state.sourceError,
    isLoading: false,
    replace: { mutateAsync: state.sourcesSave, isPending: false },
  }),
}));
const trigger = { id: "routine", agent_id: "agent" } as Trigger;
const initialActions = state.data.items;

describe("routine action consent", () => {
  beforeEach(() => {
    state.save.mockReset();
    state.sourcesSave.mockReset();
    state.sourceCurrent = true;
    state.sourceMode = undefined;
    state.sourceError = null;
    state.sourceUnavailable = [];
    state.requiredUnavailable = [];
    state.error = null;
    state.loading = false;
    state.data.can_waive = true;
    state.data.waive_blocked_reason = null;
    state.data.review_token = "review-1";
    state.data.items = initialActions.map((item) => ({ ...item, consented: false }));
    state.data.unavailable_sources = [];
    state.data.max_actions = 1000;
    state.data.review_changes = [];
  });
  it("submits only explicitly selected action identities and preserves required gates", async () => {
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    expect(screen.getByRole("checkbox", { name: "publish" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: "execute" }));
    await userEvent.click(screen.getByRole("button", { name: "Save consent" }));
    expect(state.save).toHaveBeenCalledWith([{ capability_id: "sandbox", tool_id: "execute" }]);
  });
  it("says the organization turned standing consent off, and where to turn it on", () => {
    useOrgStore.setState({ activeOrgId: "org-1" });
    state.data.can_waive = false;
    state.data.waive_blocked_reason = "organization";
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    expect(screen.getByText(/Your organization has turned off standing consent/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Open approval settings" })).toHaveAttribute(
      "href",
      "/orgs/org-1/members?tab=governance",
    );
  });
  it("says the caller lacks the permission, with no settings link they could not use", () => {
    useOrgStore.setState({ activeOrgId: "org-1" });
    state.data.can_waive = false;
    state.data.waive_blocked_reason = "permission";
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    expect(screen.getByText(/You don't have permission to decide approvals/)).toBeVisible();
    expect(screen.queryByRole("link", { name: "Open approval settings" })).toBeNull();
  });
  it("can revoke all while organization policy disallows new consent", async () => {
    state.data.can_waive = false;
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    expect(screen.getByRole("checkbox", { name: "execute" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Revoke all" }));
    expect(state.save).toHaveBeenCalledWith([], expect.any(Object));
  });
  it("drops a selection when a refreshed review describes a different version", async () => {
    const close = vi.fn();
    const { rerender } = render(<ActionConsentsDialog trigger={trigger} onClose={close} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "execute" }));
    state.data.review_token = "review-2";
    rerender(<ActionConsentsDialog trigger={trigger} onClose={close} />);
    expect(screen.getByRole("checkbox", { name: "execute" })).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Save consent" }));
    expect(state.save).toHaveBeenCalledWith([]);
  });
  it("shows a fetch failure and cannot save it as empty consent", () => {
    state.error = new Error("offline");
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    expect(screen.getByRole("alert")).toBeVisible();
    expect(screen.getByRole("button", { name: "Save consent" })).toBeDisabled();
  });
  it("selects one account's action without granting a same-named action on another account", async () => {
    state.data.items.push(
      {
        connection_id: "work",
        authorization_generation: "generation-work",
        endpoint_hash: "hash-work",
        tool_id: "send_mail",
        name: "send_mail",
        account_name: "Work",
        account_scope: "organization",
        consented: false,
        waivable: true,
      },
      {
        connection_id: "personal",
        authorization_generation: "generation-personal",
        endpoint_hash: "hash-personal",
        tool_id: "send_mail",
        name: "send_mail",
        account_name: "Private",
        account_scope: "personal",
        consented: false,
        waivable: true,
      },
    );
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    await userEvent.click(
      screen.getByRole("checkbox", {
        name: "send_mail",
        description: "Work · organization account",
      }),
    );
    expect(
      screen.getByRole("checkbox", { name: "send_mail", description: "Private · your account" }),
    ).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Save consent" }));
    expect(state.save).toHaveBeenCalledWith([
      {
        connection_id: "work",
        authorization_generation: "generation-work",
        endpoint_hash: "hash-work",
        tool_id: "send_mail",
      },
    ]);
  });
  it("groups the platform's own tools as the Builder does and keeps the agent's approvals", async () => {
    state.data.items.push(
      {
        kind: "platform",
        tool_id: "add_virtual_table_record",
        name: "add_virtual_table_record",
        group: "tables",
        consented: false,
        waivable: true,
      },
      {
        kind: "platform",
        tool_id: "delete_virtual_table_record",
        name: "delete_virtual_table_record",
        group: "tables",
        consented: false,
        waivable: false,
      },
    );
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    const platform = screen.getByRole("region", { name: "AgenticOS" });
    expect(within(platform).getByRole("group", { name: "Tables" })).toBeVisible();
    expect(screen.getByRole("checkbox", { name: "delete_virtual_table_record" })).toBeDisabled();
    expect(
      screen.getByRole("checkbox", {
        name: "add_virtual_table_record",
        description: "AgenticOS Tables",
      }),
    ).not.toBeChecked();
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Select eligible actions in Tables" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save consent" }));
    expect(state.save).toHaveBeenCalledWith([
      { kind: "platform", tool_id: "add_virtual_table_record" },
    ]);
  });
  it("explains unavailable connection inventory and still allows revocation", async () => {
    state.data.unavailable_sources = ["Work mailbox"];
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    expect(
      screen.getByText("Check these connections to review their actions: Work mailbox."),
    ).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Revoke all" }));
    expect(state.save).toHaveBeenCalledWith([], expect.any(Object));
  });
  it("copies the agent's settings over a narrower choice and names capabilities", async () => {
    state.data.items = ["execute", "write_file"].map((tool) => ({
      capability_id: "sandbox",
      capability_name: "Sandbox",
      tool_id: tool,
      name: tool,
      consented: false,
      waivable: true,
    }));
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    expect(screen.getByRole("group", { name: "Sandbox" })).toBeVisible();
    await userEvent.click(screen.getByRole("checkbox", { name: "write_file" }));
    await userEvent.click(screen.getByRole("button", { name: "Use the agent's settings" }));
    expect(screen.getByRole("checkbox", { name: "execute" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "write_file" })).toBeChecked();
  });
  it("says there is nothing to consent to when the agent asks before every action", () => {
    state.data.items = state.data.items.map((item) => ({ ...item, waivable: false }));
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    expect(
      screen.getByText("This version has no eligible actions to authorize here."),
    ).toBeVisible();
    for (const checkbox of screen.getAllByRole("checkbox")) expect(checkbox).toBeDisabled();
    expect(screen.getByRole("button", { name: "Use the agent's settings" })).toBeEnabled();
  });
  it("distinguishes an empty review from a failed connection check", () => {
    state.data.items = [];
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    expect(
      screen.getByText("This version has no eligible actions to authorize here."),
    ).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revoke all" })).toBeEnabled();
  });
  it("keeps stored exceptions read-only when policy withdraws permission to replace them", async () => {
    state.data.can_waive = false;
    state.data.items[0]!.consented = true;
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    expect(screen.getByRole("checkbox", { name: "execute" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "execute" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save consent" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Revoke all" }));
    expect(state.save).toHaveBeenCalledWith([], expect.any(Object));
  });
});

beforeEach(() => {
  state.save.mockReset();
  state.sourcesSave.mockReset();
  state.sourceCurrent = true;
  state.sourceMode = undefined;
  state.sourceError = null;
  state.sourceUnavailable = [];
  state.requiredUnavailable = [];
  state.error = null;
  state.loading = false;
  state.data.can_waive = true;
  state.data.review_token = "review-1";
  state.data.items = initialActions.map((item) => ({ ...item, consented: false }));
  state.data.max_actions = 1000;
  state.data.review_changes = [];
  state.data.unavailable_sources = [];
});

it("bulk selects a large inventory with individual exclusions and keeps mandatory approvals", async () => {
  state.data.items = Array.from({ length: 101 }, (_, index) => ({
    capability_id: "sandbox",
    tool_id: `action_${index}`,
    name: `Action ${index}`,
    consented: false,
    waivable: index !== 100,
  }));
  state.data.max_actions = 1000;
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Use the agent's settings" }));
  expect(screen.getByRole("checkbox", { name: "Action 100" })).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox", { name: "Action 4" }));
  expect(
    screen.getByRole("checkbox", { name: "Select eligible actions in Capabilities" }),
  ).toBePartiallyChecked();
  expect(screen.getAllByText("99 of 100")).toHaveLength(2);
  await userEvent.click(screen.getByRole("button", { name: "Save consent" }));
  const [keys] = state.save.mock.calls.at(-1) ?? [];
  expect(keys).toHaveLength(99);
  expect(keys).not.toContainEqual({ capability_id: "sandbox", tool_id: "action_4" });
  expect(keys).not.toContainEqual({ capability_id: "sandbox", tool_id: "action_100" });
});

it("searches actions while bulk scope stays explicit and can clear a whole group", async () => {
  state.data.items = initialActions.map((item) => ({ ...item, consented: false }));
  state.data.max_actions = 1000;
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  await userEvent.type(screen.getByRole("searchbox", { name: "Search actions" }), "execute");
  expect(screen.queryByRole("checkbox", { name: "publish" })).not.toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Select eligible actions in sandbox" }),
  );
  expect(screen.getByRole("checkbox", { name: "execute" })).toBeChecked();
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Select eligible actions in sandbox" }),
  );
  expect(screen.getByRole("checkbox", { name: "execute" })).not.toBeChecked();
  await userEvent.type(screen.getByRole("searchbox"), "missing");
  expect(screen.getByText("No actions match your search.")).toBeVisible();
});

it("offers prior choices only through an explicit new review and never selects new actions", async () => {
  state.data.items = [
    { ...initialActions[0]!, consented: false, previously_consented: true },
    { ...initialActions[1]!, consented: false, waivable: true },
  ];
  state.data.review_changes = ["version"];
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  expect(
    screen.getByText("The published agent version changed. Review its actions again."),
  ).toBeVisible();
  expect(screen.getByRole("checkbox", { name: "execute" })).not.toBeChecked();
  await userEvent.click(
    screen.getByRole("button", { name: "Reselect previously reviewed actions" }),
  );
  expect(screen.getByRole("checkbox", { name: "execute" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "publish" })).not.toBeChecked();
});

it("refuses an oversized selection visibly without dropping its items", async () => {
  state.data.items = Array.from({ length: 101 }, (_, index) => ({
    capability_id: "sandbox",
    tool_id: `action_${index}`,
    name: `Action ${index}`,
    consented: false,
    waivable: true,
  }));
  state.data.max_actions = 100;
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Use the agent's settings" }));
  expect(screen.getByRole("alert")).toHaveTextContent("101 actions selected; the limit is 100");
  expect(screen.getByRole("button", { name: "Save consent" })).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox", { name: "Action 100" }));
  expect(screen.getByRole("button", { name: "Save consent" })).toBeEnabled();
});

it("selects and clears a group from the keyboard", async () => {
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  const group = screen.getByRole("checkbox", { name: "Select eligible actions in sandbox" });
  group.focus();
  await userEvent.keyboard(" ");
  expect(screen.getByRole("checkbox", { name: "execute" })).toBeChecked();
  await userEvent.keyboard(" ");
  expect(screen.getByRole("checkbox", { name: "execute" })).not.toBeChecked();
});

it("saves the displayed sources and selected actions once before enabling a new routine", async () => {
  state.sourceCurrent = false;
  const enabled = vi.fn();
  const close = vi.fn();
  render(<ActionConsentsDialog trigger={trigger} onClose={close} onSaved={enabled} />);
  await userEvent.click(screen.getByRole("checkbox", { name: "execute" }));
  await userEvent.click(screen.getByRole("button", { name: "Enable routine" }));
  expect(state.sourcesSave).toHaveBeenCalledWith({
    review_token: "source-review",
    mode: "restricted",
  });
  expect(state.save).toHaveBeenCalledWith([{ capability_id: "sandbox", tool_id: "execute" }]);
  expect(state.sourcesSave.mock.invocationCallOrder[0]).toBeLessThan(
    state.save.mock.invocationCallOrder[0]!,
  );
  expect(enabled).toHaveBeenCalledOnce();
  expect(close).toHaveBeenCalledOnce();
});

it("leaves a newly saved routine paused when the user finishes later", async () => {
  const enabled = vi.fn();
  const close = vi.fn();
  render(<ActionConsentsDialog trigger={trigger} onClose={close} onSaved={enabled} />);
  await userEvent.click(screen.getByRole("button", { name: "Finish later" }));
  expect(close).toHaveBeenCalledOnce();
  expect(enabled).not.toHaveBeenCalled();
  expect(state.save).not.toHaveBeenCalled();
  expect(state.sourcesSave).not.toHaveBeenCalled();
});

it("does not save actions or enable after source review fails", async () => {
  state.sourceCurrent = false;
  state.sourcesSave.mockRejectedValue(new Error("Sources changed"));
  const enabled = vi.fn();
  const close = vi.fn();
  render(<ActionConsentsDialog trigger={trigger} onClose={close} onSaved={enabled} />);
  await userEvent.click(screen.getByRole("button", { name: "Enable routine" }));
  expect(state.save).not.toHaveBeenCalled();
  expect(enabled).not.toHaveBeenCalled();
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Enable routine" })).toBeEnabled();
});

it.each(["failed", "unavailable"])("does not enable with %s sources", (problem) => {
  if (problem === "failed") state.sourceError = new Error("offline");
  else state.sourceUnavailable = ["Mailbox"];
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} onSaved={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Enable routine" })).toBeDisabled();
});

it("can enable with ordinary approvals when standing consent is unavailable", async () => {
  state.data.can_waive = false;
  const enabled = vi.fn();
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} onSaved={enabled} />);
  expect(screen.getByRole("checkbox", { name: "execute" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Enable routine" }));
  expect(state.save).toHaveBeenCalledWith([]);
  expect(enabled).toHaveBeenCalledOnce();
});

it("keeps the review and selection open when actions cannot be saved", async () => {
  state.save.mockRejectedValueOnce(new Error("Action review changed"));
  const enabled = vi.fn();
  const close = vi.fn();
  render(<ActionConsentsDialog trigger={trigger} onClose={close} onSaved={enabled} />);
  await userEvent.click(screen.getByRole("checkbox", { name: "execute" }));
  await userEvent.click(screen.getByRole("button", { name: "Enable routine" }));
  expect(screen.getByRole("checkbox", { name: "execute" })).toBeChecked();
  expect(enabled).not.toHaveBeenCalled();
  expect(close).not.toHaveBeenCalled();
});

it("freezes dismissal and duplicate submission while consent is being saved", async () => {
  const completion = Promise.withResolvers<void>();
  state.save.mockReturnValueOnce(completion.promise);
  const close = vi.fn();
  render(<ActionConsentsDialog trigger={trigger} onClose={close} onSaved={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Enable routine" }));
  await userEvent.keyboard("{Escape}");
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Enable routine" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Finish later" })).toBeDisabled();
  await act(async () => completion.resolve());
  await waitFor(() => expect(close).toHaveBeenCalledOnce());
});

it("can review sources without standing-consent permission or changing stored action grants", async () => {
  state.sourceCurrent = false;
  state.data.can_waive = false;
  state.data.items[0]!.consented = true;
  const close = vi.fn();
  render(<ActionConsentsDialog trigger={trigger} onClose={close} />);
  await userEvent.click(screen.getByRole("button", { name: "Save consent" }));
  expect(state.sourcesSave).toHaveBeenCalledWith({
    review_token: "source-review",
    mode: "restricted",
  });
  expect(state.save).not.toHaveBeenCalled();
  expect(close).toHaveBeenCalledOnce();
});

it("retries a failed action review before offering another consent", async () => {
  state.error = new Error("offline");
  state.retry.mockClear();
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(state.retry).toHaveBeenCalledOnce();
  expect(state.save).not.toHaveBeenCalled();
});

it("can dismiss an idle access review with Escape", async () => {
  const close = vi.fn();
  render(<ActionConsentsDialog trigger={trigger} onClose={close} />);
  await userEvent.keyboard("{Escape}");
  expect(close).toHaveBeenCalledOnce();
});

it("waits for the action inventory instead of presenting an empty selection", () => {
  state.loading = true;
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.queryByRole("checkbox", { name: "execute" })).toBeNull();
});

it("uses the compatibility selection limit when the server omits it", async () => {
  delete state.data.max_actions;
  state.data.items = Array.from({ length: 101 }, (_, index) => ({
    capability_id: "sandbox",
    tool_id: `action_${index}`,
    name: `Action ${index}`,
    consented: false,
    waivable: true,
  }));
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  // Nothing about the count is said until it is over the limit.
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Use the agent's settings" }));
  expect(screen.getByRole("alert")).toHaveTextContent("101 actions selected; the limit is 100");
});

it("explains the agent's settings on hover and heads the actions it allows", async () => {
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  expect(
    screen.getByRole("heading", { name: "Allow these actions to run without asking for approval" }),
  ).toBeVisible();
  await userEvent.hover(screen.getByRole("button", { name: "Use the agent's settings" }));
  expect(await screen.findByRole("tooltip")).toHaveTextContent("only narrow");
});

it("can change source inheritance without permission to preapprove actions", async () => {
  state.data.can_waive = false;
  state.sourceUnavailable = ["Optional mailbox"];
  const close = vi.fn();
  render(<ActionConsentsDialog trigger={trigger} onClose={close} />);
  await userEvent.click(screen.getByRole("button", { name: "Follow source settings" }));
  const save = screen.getByRole("button", { name: "Save access mode" });
  expect(save).toBeEnabled();
  await userEvent.click(save);
  expect(state.sourcesSave).toHaveBeenCalledWith({
    review_token: "source-review",
    mode: "follow_agent",
  });
  expect(state.save).not.toHaveBeenCalled();
  expect(close).toHaveBeenCalledOnce();
});

it("does not discard an action catalog failure in follow mode", () => {
  state.sourceMode = "follow_agent";
  state.sourceUnavailable = ["Optional mailbox"];
  state.error = new Error("Unused action catalog unavailable");
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByRole("alert")).toBeVisible();
  expect(screen.queryByRole("checkbox", { name: "execute" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Revoke all" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Save access mode" })).toBeDisabled();
});

it("blocks enabling follow mode when the action catalog is unavailable", async () => {
  state.sourceMode = "follow_agent";
  state.sourceCurrent = false;
  state.error = new Error("Unused action catalog unavailable");
  const enabled = vi.fn();
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} onSaved={enabled} />);
  await userEvent.click(screen.getByRole("button", { name: "Enable routine" }));
  expect(state.sourcesSave).not.toHaveBeenCalled();
  expect(state.save).not.toHaveBeenCalled();
  expect(enabled).not.toHaveBeenCalled();
});

it.each(["required", "legacy-unclassified"])(
  "does not save or enable follow mode with %s unavailable sources",
  async (classification) => {
    state.sourceMode = "follow_agent";
    state.sourceCurrent = false;
    state.sourceUnavailable = ["Creator identity"];
    state.requiredUnavailable = classification === "required" ? ["Creator identity"] : undefined;
    const enabled = vi.fn();
    const close = vi.fn();
    render(<ActionConsentsDialog trigger={trigger} onClose={close} onSaved={enabled} />);
    const save = screen.getByRole("button", { name: "Enable routine" });
    expect(save).toBeDisabled();
    await userEvent.click(save);
    expect(state.sourcesSave).not.toHaveBeenCalled();
    expect(state.save).not.toHaveBeenCalled();
    expect(enabled).not.toHaveBeenCalled();
    expect(close).not.toHaveBeenCalled();
  },
);

it("allows explicit optional gaps while enabling follow mode", async () => {
  state.sourceMode = "follow_agent";
  state.sourceCurrent = false;
  state.sourceUnavailable = ["Optional mailbox"];
  state.requiredUnavailable = [];
  const enabled = vi.fn();
  render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} onSaved={enabled} />);
  await userEvent.click(screen.getByRole("button", { name: "Enable routine" }));
  expect(state.sourcesSave).toHaveBeenCalledWith({
    review_token: "source-review",
    mode: "follow_agent",
  });
  expect(state.save).toHaveBeenCalledWith([]);
  expect(enabled).toHaveBeenCalledOnce();
});
