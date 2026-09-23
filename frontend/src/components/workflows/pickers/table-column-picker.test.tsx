import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TableColumnPicker } from "./table-column-picker";
import type { TableIORef } from "@/lib/workflows/types";

const useWorkflowTablesMock = vi.fn();
const useWorkflowTableMock = vi.fn();

vi.mock("@/hooks", () => ({
  useWorkflowTables: () => useWorkflowTablesMock(),
  useWorkflowTable: (id: string | null) => useWorkflowTableMock(id),
}));

const TABLES = [
  { id: "t1", name: "Leads", schema_version: 2 },
  { id: "t2", name: "Orders", schema_version: 1 },
];
const TABLE_T1 = {
  id: "t1",
  name: "Leads",
  schema_version: 2,
  columns: [
    { id: "c1", label: "Email", type: "text", archived: false },
    { id: "c2", label: "Name", type: "text", archived: false },
    { id: "c3", label: "Retired", type: "text", archived: true },
  ],
};

function ref(overrides: Partial<TableIORef> = {}): TableIORef {
  return { kind: "table", table_id: "t1", column_ids: null, schema_version: 2, ...overrides };
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkflowTablesMock.mockReturnValue({ tables: TABLES, isLoading: false });
  useWorkflowTableMock.mockReturnValue({ table: TABLE_T1, isLoading: false });
});

function mount(
  value: TableIORef | null,
  props: Partial<{ disabled: boolean; error: string }> = {},
) {
  const onChange = vi.fn();
  render(<TableColumnPicker value={value} onChange={onChange} {...props} />);
  return onChange;
}

describe("TableColumnPicker", () => {
  it("choosing a table pins it to its current schema, all columns", async () => {
    useWorkflowTableMock.mockReturnValue({ table: null, isLoading: false });
    const onChange = mount(null);

    await userEvent.click(screen.getByRole("combobox", { name: "Table" }));
    await userEvent.click(screen.getByRole("option", { name: "Orders" }));

    expect(onChange).toHaveBeenCalledWith({
      kind: "table",
      table_id: "t2",
      column_ids: null,
      schema_version: 1,
    });
  });

  it("keeps a bound table visible when it names no table the caller can see", () => {
    useWorkflowTableMock.mockReturnValue({ table: null, isLoading: false });
    mount(ref({ table_id: "gone" }));

    expect(screen.getByText("The bound table is no longer available.")).toBeVisible();
    expect(screen.getByText("gone")).toBeVisible();
    expect(screen.queryByText("Columns")).toBeNull();
  });

  it("shows the schema-drift banner and rebinds to the current schema", async () => {
    const onChange = mount(ref({ schema_version: 1, column_ids: ["c1"] }));

    expect(screen.getByText("This table's schema changed since this was bound.")).toBeVisible();
    expect(screen.queryByRole("checkbox", { name: "Email" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Rebind to the current schema" }));
    expect(onChange).toHaveBeenCalledWith({
      kind: "table",
      table_id: "t1",
      column_ids: null,
      schema_version: 2,
    });
  });

  it("renders the current schema's live columns, archived ones excluded", () => {
    mount(ref());

    expect(screen.getByRole("checkbox", { name: "All columns" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("checkbox", { name: "Email" })).toBeVisible();
    expect(screen.getByRole("checkbox", { name: "Name" })).toBeVisible();
    expect(screen.queryByRole("checkbox", { name: "Retired" })).toBeNull();
  });

  it("narrowing off one column writes the explicit remaining list", async () => {
    const onChange = mount(ref({ column_ids: null }));

    await userEvent.click(screen.getByRole("checkbox", { name: "Name" }));

    expect(onChange).toHaveBeenCalledWith({
      kind: "table",
      table_id: "t1",
      column_ids: ["c1"],
      schema_version: 2,
    });
  });

  it("ticking every column collapses back to all-columns (null)", async () => {
    const onChange = mount(ref({ column_ids: ["c1"] }));

    expect(screen.getByRole("checkbox", { name: "Name" })).toHaveAttribute("aria-checked", "false");
    await userEvent.click(screen.getByRole("checkbox", { name: "Name" }));

    expect(onChange).toHaveBeenCalledWith({
      kind: "table",
      table_id: "t1",
      column_ids: null,
      schema_version: 2,
    });
  });

  it("the all-columns row resets a narrowed selection", async () => {
    const onChange = mount(ref({ column_ids: ["c1"] }));

    await userEvent.click(screen.getByRole("checkbox", { name: "All columns" }));

    expect(onChange).toHaveBeenCalledWith({
      kind: "table",
      table_id: "t1",
      column_ids: null,
      schema_version: 2,
    });
  });

  it("shows a loading notice while the table's columns are fetched", () => {
    useWorkflowTableMock.mockReturnValue({ table: null, isLoading: true });
    mount(ref());

    expect(screen.getByText("Loading columns…")).toBeVisible();
    expect(screen.queryByRole("checkbox", { name: "All columns" })).toBeNull();
  });

  it("says so when the organization has no tables", () => {
    useWorkflowTablesMock.mockReturnValue({ tables: [], isLoading: false });
    mount(null);

    expect(screen.getByText("No tables to choose from.")).toBeVisible();
    expect(screen.queryByText("Columns")).toBeNull();
  });

  it("shows a field-scoped validation message", () => {
    mount(ref(), { error: "Required" });
    expect(screen.getByText("Required")).toBeVisible();
  });

  it("is inert for a caller who may not edit the workflow", () => {
    mount(ref(), { disabled: true });

    expect(screen.getByRole("combobox", { name: "Table" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Email" })).toBeDisabled();
  });
});
