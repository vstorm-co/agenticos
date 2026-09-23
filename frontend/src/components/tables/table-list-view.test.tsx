import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TableListView } from "./table-list-view";
import type { CellValue, ColumnDef, RecordRead } from "@/types/tables";

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
    label: "Role",
    type: "text",
    nullable: true,
    default: null,
    options: [],
    archived: false,
  },
  {
    id: "c3",
    label: "Paid",
    type: "boolean",
    nullable: true,
    default: null,
    options: [],
    archived: false,
  },
  {
    id: "c4",
    label: "Extra",
    type: "text",
    nullable: true,
    default: null,
    options: [],
    archived: false,
  },
];

function record(values: Record<string, CellValue>): RecordRead {
  return {
    id: "r1",
    table_id: "t1",
    external_id: null,
    schema_version: 1,
    values,
    revision: 1,
    created_at: "2026-09-23T00:00:00Z",
  };
}

describe("TableListView", () => {
  it("shows a loading skeleton when loading with no records yet", () => {
    const { container } = render(
      <TableListView columns={columns} records={[]} isLoading onOpenRecord={vi.fn()} />,
    );
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("shows the empty state when not loading and there are no records", () => {
    render(
      <TableListView columns={columns} records={[]} isLoading={false} onOpenRecord={vi.fn()} />,
    );
    expect(screen.getByText(/no records yet/i)).toBeInTheDocument();
  });

  it("shows the title from the first column and up to three secondary values", () => {
    render(
      <TableListView
        columns={columns}
        records={[record({ c1: "Ada", c2: "Engineer", c3: true, c4: "x" })]}
        isLoading={false}
        onOpenRecord={vi.fn()}
      />,
    );
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.getByText("Engineer · True · x")).toBeInTheDocument();
  });

  it("renders a false boolean secondary value", () => {
    render(
      <TableListView
        columns={columns}
        records={[record({ c1: "Ada", c3: false })]}
        isLoading={false}
        onOpenRecord={vi.fn()}
      />,
    );
    expect(screen.getByText("False")).toBeInTheDocument();
  });

  it("falls back to the record id when the title column has no visible columns", () => {
    render(
      <TableListView
        columns={[]}
        records={[record({})]}
        isLoading={false}
        onOpenRecord={vi.fn()}
      />,
    );
    expect(screen.getByText("r1")).toBeInTheDocument();
  });

  it("drops empty secondary values from the summary line", () => {
    render(
      <TableListView
        columns={columns}
        records={[record({ c1: "Ada" })]}
        isLoading={false}
        onOpenRecord={vi.fn()}
      />,
    );
    // c2/c3/c4 all empty - the secondary line renders nothing.
    expect(screen.queryByText("·")).not.toBeInTheDocument();
  });

  it("opens the record when its row is clicked", async () => {
    const onOpenRecord = vi.fn();
    const user = userEvent.setup();
    const rec = record({ c1: "Ada" });
    render(
      <TableListView
        columns={columns}
        records={[rec]}
        isLoading={false}
        onOpenRecord={onOpenRecord}
      />,
    );

    await user.click(screen.getByText("Ada"));

    expect(onOpenRecord).toHaveBeenCalledWith(rec);
  });
});
