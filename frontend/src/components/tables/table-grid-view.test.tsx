import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TableGridView } from "./table-grid-view";
import type { ColumnDef, RecordRead } from "@/types/tables";

const columns: ColumnDef[] = [
  {
    id: "c1",
    label: "Name",
    type: "text",
    nullable: true,
    default: null,
    options: [],
    archived: false,
  },
  {
    id: "c2",
    label: "Tags",
    type: "multi_select",
    nullable: true,
    default: null,
    options: [{ id: "o1", label: "Rush", archived: false }],
    archived: false,
  },
];

const records: RecordRead[] = [
  {
    id: "r1",
    table_id: "t1",
    external_id: null,
    schema_version: 1,
    values: { c1: "Ada", c2: ["o1"] },
    revision: 1,
    created_at: "2026-09-23T00:00:00Z",
  },
];

describe("TableGridView", () => {
  it("renders one column per live column and one row per record", () => {
    render(
      <TableGridView
        columns={columns}
        records={records}
        isLoading={false}
        sort={{ by: "created_at", direction: "asc" }}
        onSort={vi.fn()}
        onOpenRecord={vi.fn()}
      />,
    );
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.getByText("Rush")).toBeInTheDocument();
  });

  it("renders a boolean cell through the cells translations", () => {
    const boolColumn: ColumnDef = {
      id: "c3",
      label: "Paid",
      type: "boolean",
      nullable: true,
      default: null,
      options: [],
      archived: false,
    };
    render(
      <TableGridView
        columns={[boolColumn]}
        records={[{ ...records[0], values: { c3: true } } as RecordRead]}
        isLoading={false}
        sort={{ by: "created_at", direction: "asc" }}
        onSort={vi.fn()}
        onOpenRecord={vi.fn()}
      />,
    );
    expect(screen.getByText("True")).toBeInTheDocument();
  });

  it("renders a false boolean cell", () => {
    const boolColumn: ColumnDef = {
      id: "c3",
      label: "Paid",
      type: "boolean",
      nullable: true,
      default: null,
      options: [],
      archived: false,
    };
    render(
      <TableGridView
        columns={[boolColumn]}
        records={[{ ...records[0], values: { c3: false } } as RecordRead]}
        isLoading={false}
        sort={{ by: "created_at", direction: "asc" }}
        onSort={vi.fn()}
        onOpenRecord={vi.fn()}
      />,
    );
    expect(screen.getByText("False")).toBeInTheDocument();
  });

  it("shows an em dash for an empty cell", () => {
    render(
      <TableGridView
        columns={[columns[0] as ColumnDef]}
        records={[{ ...records[0], values: {} } as RecordRead]}
        isLoading={false}
        sort={{ by: "created_at", direction: "asc" }}
        onSort={vi.fn()}
        onOpenRecord={vi.fn()}
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("opens the record when a row is clicked", async () => {
    const onOpenRecord = vi.fn();
    const user = userEvent.setup();
    render(
      <TableGridView
        columns={columns}
        records={records}
        isLoading={false}
        sort={{ by: "created_at", direction: "asc" }}
        onSort={vi.fn()}
        onOpenRecord={onOpenRecord}
      />,
    );

    await user.click(screen.getByText("Ada"));

    expect(onOpenRecord).toHaveBeenCalledWith(records[0]);
  });

  it("a text column is sortable and reports the flipped direction", async () => {
    const onSort = vi.fn();
    const user = userEvent.setup();
    render(
      <TableGridView
        columns={columns}
        records={records}
        isLoading={false}
        sort={{ by: "c1", direction: "asc" }}
        onSort={onSort}
        onOpenRecord={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Name" }));

    expect(onSort).toHaveBeenCalledWith({ by: "c1", direction: "desc" });
  });

  it("a multi_select column is not sortable", () => {
    render(
      <TableGridView
        columns={columns}
        records={records}
        isLoading={false}
        sort={{ by: "created_at", direction: "asc" }}
        onSort={vi.fn()}
        onOpenRecord={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Tags" })).not.toBeInTheDocument();
  });

  it("shows the empty state when there are no records", () => {
    render(
      <TableGridView
        columns={columns}
        records={[]}
        isLoading={false}
        sort={{ by: "created_at", direction: "asc" }}
        onSort={vi.fn()}
        onOpenRecord={vi.fn()}
      />,
    );
    expect(screen.getByText(/no records yet/i)).toBeInTheDocument();
  });
});
