import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { TABLE_SYSTEM_COLUMNS } from "@/lib/table-system-columns";
import type { ColumnDef, RecordSort } from "@/types/tables";
import { RecordSortPopover } from "./record-sort-popover";

const title: ColumnDef = {
  id: "name",
  label: "Name",
  type: "text",
  nullable: true,
  default: null,
  options: [],
  archived: false,
};
const columns: ColumnDef[] = [
  title,
  { ...title, id: "tags", label: "Tags", type: "multi_select" },
  { ...title, id: "old", label: "Archived column", archived: true },
  ...TABLE_SYSTEM_COLUMNS,
];
function Harness({ change }: { change: (sort: RecordSort) => void }) {
  const [sort, setSort] = useState<RecordSort>({ by: "created_at", direction: "asc" });
  return (
    <RecordSortPopover
      columns={columns}
      sort={sort}
      onChange={(next) => {
        setSort(next);
        change(next);
      }}
    />
  );
}

describe("record sorting", () => {
  it("changes the ordering column and direction and can restore the default", async () => {
    const user = userEvent.setup();
    const change = vi.fn();
    render(<Harness change={change} />);
    await user.click(screen.getByRole("button", { name: "Sort" }));
    expect(screen.getByRole("button", { name: "Default order: oldest first" })).toBeDisabled();
    await user.click(screen.getByRole("combobox", { name: "Sort by" }));
    await user.click(screen.getByRole("option", { name: "Name" }));
    expect(change).toHaveBeenLastCalledWith({ by: "name", direction: "asc" });
    await user.click(screen.getByRole("combobox", { name: "Direction" }));
    await user.click(screen.getByRole("option", { name: "Descending" }));
    expect(change).toHaveBeenLastCalledWith({ by: "name", direction: "desc" });
    await user.click(screen.getByRole("button", { name: "Default order: oldest first" }));
    expect(change).toHaveBeenLastCalledWith({ by: "created_at", direction: "asc" });
  });
  it("offers sortable hidden columns and dates, excluding unsupported fields and authors", async () => {
    const user = userEvent.setup();
    const change = vi.fn();
    render(<Harness change={change} />);
    await user.click(screen.getByRole("button", { name: "Sort" }));
    await user.click(screen.getByRole("combobox", { name: "Sort by" }));
    expect(screen.queryByRole("option", { name: "Tags" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Archived column" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Created by" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Updated by" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: "Last updated" }));
    expect(change).toHaveBeenLastCalledWith({ by: "updated_at", direction: "asc" });
  });
});
