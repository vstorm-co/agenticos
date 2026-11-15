import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ActionConsentsDialog } from "./action-consents-dialog";
import type { RoutineActionOptions } from "@/lib/routine-actions-api";
import type { Trigger } from "@/types/triggers";

vi.mock("./source-consents-panel", () => ({ SourceConsentsPanel: () => null }));

const state = vi.hoisted(() => ({
  data: {
    can_waive: true,
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
  save: vi.fn(),
  retry: vi.fn(),
}));
vi.mock("@/hooks/use-routine-actions", () => ({
  useRoutineActions: () => ({
    data: state.data,
    isLoading: false,
    error: state.error,
    replace: { mutate: state.save, isPending: false },
    refetch: state.retry,
  }),
}));
const trigger = { id: "routine", agent_id: "agent" } as Trigger;
const initialActions = state.data.items;

describe("routine action consent", () => {
  beforeEach(() => {
    state.save.mockReset();
    state.error = null;
    state.data.can_waive = true;
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
    expect(state.save).toHaveBeenCalledWith(
      [{ capability_id: "sandbox", tool_id: "execute" }],
      expect.any(Object),
    );
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
    expect(state.save).toHaveBeenCalledWith([], expect.any(Object));
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
    expect(state.save).toHaveBeenCalledWith(
      [
        {
          connection_id: "work",
          authorization_generation: "generation-work",
          endpoint_hash: "hash-work",
          tool_id: "send_mail",
        },
      ],
      expect.any(Object),
    );
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
  state.error = null;
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
  await userEvent.click(screen.getByRole("checkbox", { name: "Select all eligible actions" }));
  expect(screen.getByRole("checkbox", { name: "Action 100" })).not.toBeChecked();
  await userEvent.click(screen.getByRole("checkbox", { name: "Action 4" }));
  expect(
    screen.getByRole("checkbox", { name: "Select all eligible actions" }),
  ).toBePartiallyChecked();
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
  await userEvent.click(screen.getByRole("checkbox", { name: "Select all eligible actions" }));
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
