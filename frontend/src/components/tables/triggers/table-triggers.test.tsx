import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ColumnDef, TableTriggerAdmission, TableTriggerRead } from "@/types/tables";

import { TableTriggersPanel } from "./table-triggers-panel";

const hook = {
  triggers: [] as TableTriggerRead[],
  isLoading: false,
  setActive: { mutate: vi.fn(), isPending: false },
};
const admissions = { admissions: [] as TableTriggerAdmission[], total: 0, isLoading: false };

vi.mock("@/hooks", () => ({
  useTableTriggers: () => hook,
  useTableTriggerAdmissions: () => admissions,
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

function trigger(overrides: Partial<TableTriggerRead> = {}): TableTriggerRead {
  return {
    id: "t1",
    table_id: "tbl",
    workflow_id: "wf",
    workflow_name: "Lead follow-up",
    workflow_version_id: "v2",
    version_number: 2,
    node_instance_id: "n1",
    revision: 1,
    filters: [],
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
});

describe("TableTriggersPanel", () => {
  it("waits for the list, then says what an empty one means", () => {
    hook.isLoading = true;
    const { rerender } = render(<TableTriggersPanel tableId="tbl" columns={COLUMNS} canEdit />);
    expect(screen.queryByText(/No workflow starts from this table/)).toBeNull();
    hook.isLoading = false;
    rerender(<TableTriggersPanel tableId="tbl" columns={COLUMNS} canEdit />);
    expect(screen.getByText(/No workflow starts from this table/)).toBeTruthy();
  });

  it("pauses a trigger, links its workflow and shows what it decided", async () => {
    hook.triggers = [
      trigger({ filters: [{ column_id: "c-score", op: "gt", value: 1 }] }),
      trigger({
        id: "t2",
        workflow_id: "wf2",
        workflow_name: "Everything",
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
    render(<TableTriggersPanel tableId="tbl" columns={COLUMNS} canEdit />);

    expect(screen.getByText("When Score matches")).toBeTruthy();
    expect(screen.getByText("When gone matches")).toBeTruthy();
    expect(screen.getAllByText("Runs v2")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Lead follow-up" }).getAttribute("href")).toBe(
      "/workflows/wf",
    );
    await userEvent.click(screen.getByRole("switch", { name: "Everything is on" }));
    expect(hook.setActive.mutate).toHaveBeenCalledWith({ id: "t2", active: true });
    // Made and changed by publishing its workflow, not here.
    expect(screen.queryByRole("button", { name: /New trigger|Edit|Delete/ })).toBeNull();
    expect(screen.getByText(/New table record/)).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "History of Lead follow-up" }));
    const history = await screen.findByRole("dialog");
    expect(within(history).getByText("Started a run")).toBeTruthy();
    expect(within(history).getByText(/It would have started itself/)).toBeTruthy();
    expect(within(history).getByRole("link", { name: "Open the run" }).getAttribute("href")).toBe(
      "/workflows/wf/runs/r1",
    );
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
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

  it("shows a member who cannot edit a switched-off trigger without its switch", () => {
    hook.triggers = [trigger({ is_active: false })];
    render(<TableTriggersPanel tableId="tbl" columns={COLUMNS} canEdit={false} />);
    expect(screen.getByText("Off")).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
  });
});
