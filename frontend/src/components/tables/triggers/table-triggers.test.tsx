import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowRead } from "@/lib/workflows/types";
import type { ColumnDef, TableTriggerAdmission, TableTriggerRead } from "@/types/tables";

import { TableTriggersPanel } from "./table-triggers-panel";
import { operand, TriggerDialog } from "./trigger-dialog";

const hook = {
  triggers: [] as TableTriggerRead[],
  isLoading: false,
  create: { mutate: vi.fn(), isPending: false },
  update: { mutate: vi.fn(), isPending: false },
  remove: { mutate: vi.fn(), isPending: false },
};
const admissions = { admissions: [] as TableTriggerAdmission[], total: 0, isLoading: false };
const workflows = { workflows: [] as WorkflowRead[] };

vi.mock("@/hooks", () => ({
  useTableTriggers: () => hook,
  useTableTriggerAdmissions: () => admissions,
  useWorkflows: () => workflows,
}));

const COLUMNS: ColumnDef[] = [
  {
    id: "c-email",
    label: "Email",
    type: "text",
    nullable: true,
    default: null,
    options: [],
    archived: false,
  },
  {
    id: "c-score",
    label: "Score",
    type: "integer",
    nullable: true,
    default: null,
    options: [],
    archived: false,
  },
  {
    id: "c-vip",
    label: "VIP",
    type: "boolean",
    nullable: true,
    default: null,
    options: [],
    archived: false,
  },
  {
    id: "c-old",
    label: "Old",
    type: "text",
    nullable: true,
    default: null,
    options: [],
    archived: true,
  },
];

const WORKFLOW = {
  id: "wf",
  name: "Lead follow-up",
  status: "published",
  current_version_id: "v2",
} as WorkflowRead;

function trigger(overrides: Partial<TableTriggerRead> = {}): TableTriggerRead {
  return {
    id: "t1",
    table_id: "tbl",
    workflow_id: "wf",
    workflow_name: "Lead follow-up",
    workflow_version_id: "v2",
    version_number: 2,
    name: null,
    revision: 1,
    filters: [],
    input_mapping: { email: "c-email" },
    execution_principal_user_id: "u1",
    is_active: true,
    activated_at: "2026-09-29T10:00:00Z",
    created_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  hook.triggers = [];
  hook.isLoading = false;
  admissions.admissions = [];
  admissions.isLoading = false;
  workflows.workflows = [
    WORKFLOW,
    { ...WORKFLOW, id: "draft", name: "Draft", current_version_id: null } as WorkflowRead,
  ];
});

describe("operand", () => {
  it("stores a filter's value as its column's type", () => {
    expect(operand(COLUMNS[1], "gt", "7")).toBe(7);
    expect(operand(COLUMNS[1], "gt", "seven")).toBe("seven");
    expect(operand(COLUMNS[2], "eq", "true")).toBe(true);
    expect(operand(COLUMNS[0], "eq", "a")).toBe("a");
    expect(operand(undefined, "is_null", "false")).toBe(false);
    expect(operand(undefined, "is_null", "")).toBe(true);
  });
});

describe("TriggerDialog", () => {
  it("creates a trigger on a published workflow, with filters and a mapping", async () => {
    const onSubmit = vi.fn();
    render(
      <TriggerDialog
        columns={COLUMNS}
        workflows={workflows.workflows}
        onOpenChange={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByRole("button", { name: "Create" })).toHaveProperty("disabled", true);
    await userEvent.click(screen.getByRole("combobox", { name: "Workflow" }));
    expect(screen.queryByRole("option", { name: "Draft" })).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: "Lead follow-up" }));
    await userEvent.type(screen.getByLabelText("Name"), "Hot leads");

    await userEvent.click(screen.getByRole("button", { name: "Add a filter" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Column of filter 1" }));
    await userEvent.click(screen.getByRole("option", { name: "Score" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Operator of filter 1" }));
    await userEvent.click(screen.getByRole("option", { name: "is greater than" }));
    // A condition with nothing to compare against is not one.
    expect(screen.getByRole("button", { name: "Create" })).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByLabelText("Value of filter 1"), { target: { value: "80" } });

    await userEvent.click(screen.getByRole("button", { name: "Add a value" }));
    fireEvent.change(screen.getByLabelText("Key of value 2"), { target: { value: "by" } });
    await userEvent.click(screen.getByRole("combobox", { name: "Source of value 2" }));
    await userEvent.click(screen.getByRole("option", { name: "Score" }));

    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(onSubmit).toHaveBeenCalledWith({
      workflow_id: "wf",
      name: "Hot leads",
      filters: [{ column_id: "c-score", op: "gt", value: 80 }],
      input_mapping: { record_id: "@record_id", by: "c-score" },
    });
  });

  it("edits a trigger it was opened on, removing a filter and a value", async () => {
    const onSubmit = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <TriggerDialog
        columns={COLUMNS}
        workflows={workflows.workflows}
        trigger={trigger({
          name: "Named",
          filters: [
            { column_id: "c-email", op: "is_null", value: false },
            { column_id: "c-score", op: "eq", value: null },
          ],
          input_mapping: { a: "c-email", b: "@author" },
        })}
        onOpenChange={onOpenChange}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByRole("combobox", { name: "Workflow" })).toHaveProperty("disabled", true);
    expect(screen.getByLabelText("Value of filter 1")).toHaveProperty("disabled", true);
    await userEvent.click(screen.getByRole("button", { name: "Remove filter 2" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove value 2" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).toHaveBeenCalledWith({
      workflow_id: "wf",
      name: "Named",
      filters: [{ column_id: "c-email", op: "is_null", value: false }],
      input_mapping: { a: "c-email" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("says when nothing is published, and maps the record's id on a table with no columns", async () => {
    render(<TriggerDialog columns={[]} workflows={[]} onOpenChange={vi.fn()} onSubmit={vi.fn()} />);
    expect(screen.getByText(/Publish a workflow first/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add a filter" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("combobox", { name: "Source of value 1" }).textContent).toContain(
      "The record's id",
    );
  });
});

describe("TableTriggersPanel", () => {
  it("waits for the list, then says what an empty one means", () => {
    hook.isLoading = true;
    const { rerender } = render(<TableTriggersPanel tableId="tbl" columns={COLUMNS} canEdit />);
    expect(screen.queryByText(/No workflow runs/)).toBeNull();
    hook.isLoading = false;
    rerender(<TableTriggersPanel tableId="tbl" columns={COLUMNS} canEdit />);
    expect(screen.getByText(/No workflow runs/)).toBeTruthy();
  });

  it("creates a trigger through the dialog", async () => {
    hook.create.mutate.mockImplementation((_body, options) => options.onSuccess());
    render(<TableTriggersPanel tableId="tbl" columns={COLUMNS} canEdit />);
    await userEvent.click(screen.getByRole("button", { name: "New trigger" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Workflow" }));
    await userEvent.click(screen.getByRole("option", { name: "Lead follow-up" }));
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(hook.create.mutate).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("switches, edits, moves, shows the history of and deletes a trigger", async () => {
    hook.triggers = [
      trigger({
        workflow_version_id: "v1",
        version_number: 1,
        filters: [{ column_id: "c-score", op: "gt", value: 1 }],
      }),
      trigger({
        id: "t2",
        name: "Everything",
        is_active: false,
        filters: [{ column_id: "gone", op: "eq", value: 1 }],
      }),
    ];
    admissions.admissions = [
      {
        id: "a1",
        trigger_revision: 1,
        status: "queued",
        reason: null,
        workflow_run_id: "r1",
        created_at: "2026-09-29T10:00:00Z",
      },
      {
        id: "a2",
        trigger_revision: 1,
        status: "blocked",
        reason: "cycle",
        workflow_run_id: null,
        created_at: "2026-09-29T10:00:00Z",
      },
    ];
    hook.update.mutate.mockImplementation((_args, options) => options?.onSuccess?.());
    render(<TableTriggersPanel tableId="tbl" columns={COLUMNS} canEdit />);

    expect(screen.getByText("When Score matches")).toBeTruthy();
    expect(screen.getByText("When gone matches")).toBeTruthy();
    await userEvent.click(screen.getByRole("switch", { name: "Everything is on" }));
    expect(hook.update.mutate).toHaveBeenCalledWith({ id: "t2", body: { is_active: true } });
    await userEvent.click(screen.getByRole("button", { name: "Use the live version" }));
    expect(hook.update.mutate).toHaveBeenCalledWith({
      id: "t1",
      body: { pin_current_version: true },
    });

    await userEvent.click(screen.getByRole("button", { name: "Edit Lead follow-up" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(hook.update.mutate).toHaveBeenLastCalledWith(
      { id: "t1", body: expect.not.objectContaining({ workflow_id: expect.anything() }) },
      expect.anything(),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await userEvent.click(screen.getByRole("button", { name: "History of Lead follow-up" }));
    const history = await screen.findByRole("dialog");
    expect(within(history).getByText("Started a run")).toBeTruthy();
    expect(within(history).getByText(/It would have started itself/)).toBeTruthy();
    expect(within(history).getByRole("link", { name: "Open the run" }).getAttribute("href")).toBe(
      "/workflows/wf/runs/r1",
    );
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await userEvent.click(screen.getByRole("button", { name: "Delete Lead follow-up" }));
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(hook.remove.mutate).toHaveBeenCalledWith("t1");
  });

  it("closes the dialog and the delete confirmation when they are cancelled", async () => {
    hook.triggers = [trigger()];
    render(<TableTriggersPanel tableId="tbl" columns={COLUMNS} canEdit />);

    await userEvent.click(screen.getByRole("button", { name: "New trigger" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await userEvent.click(screen.getByRole("button", { name: "Delete Lead follow-up" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(hook.remove.mutate).not.toHaveBeenCalled();
  });

  it("shows a history still loading, or empty", async () => {
    hook.triggers = [trigger()];
    admissions.isLoading = true;
    const { rerender } = render(
      <TableTriggersPanel tableId="tbl" columns={COLUMNS} canEdit={false} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "History of Lead follow-up" }));
    expect(screen.queryByText(/No record has been added/)).toBeNull();
    admissions.isLoading = false;
    rerender(<TableTriggersPanel tableId="tbl" columns={COLUMNS} canEdit={false} />);
    expect(await screen.findByText(/No record has been added/)).toBeTruthy();
  });

  it("shows a member who cannot edit a switched-off trigger without its controls", () => {
    hook.triggers = [trigger({ is_active: false, workflow_version_id: "v1" })];
    render(<TableTriggersPanel tableId="tbl" columns={COLUMNS} canEdit={false} />);
    expect(screen.getByText("Off")).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.queryByRole("button", { name: "Use the live version" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New trigger" })).toBeNull();
  });
});
