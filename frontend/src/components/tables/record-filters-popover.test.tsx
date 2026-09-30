import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecordFiltersPopover } from "./record-filters-popover";
import type { ColumnDef, RecordFilter } from "@/types/tables";

const base = { nullable: true, default: null, options: [], archived: false };
const columns: ColumnDef[] = [
  { ...base, id: "name", label: "Name", type: "text" },
  { ...base, id: "seats", label: "Seats", type: "integer" },
  { ...base, id: "paid", label: "Paid", type: "boolean" },
  { ...base, id: "due", label: "Due", type: "date" },
  {
    ...base,
    id: "tier",
    label: "Tier",
    type: "single_select",
    options: [
      { id: "free", label: "Free", archived: false },
      { id: "team", label: "Team", archived: false },
    ],
  },
  {
    ...base,
    id: "tags",
    label: "Tags",
    type: "multi_select",
    options: [{ id: "rush", label: "Rush", archived: false }],
  },
];

function open(filters: RecordFilter[], onChange = vi.fn(), cols = columns) {
  render(<RecordFiltersPopover columns={cols} filters={filters} onChange={onChange} />);
  fireEvent.click(screen.getByRole("button", { name: /filter/i }));
  return onChange;
}

async function pick(combobox: HTMLElement, option: string) {
  fireEvent.click(combobox);
  fireEvent.click(await screen.findByRole("option", { name: option }));
}

describe("RecordFiltersPopover", () => {
  it("counts only the complete conditions on its button", () => {
    render(
      <RecordFiltersPopover
        columns={columns}
        filters={[
          { column_id: "seats", op: "gt", value: 3 },
          { column_id: "name", op: "contains", value: null },
        ]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /filter/i })).toHaveTextContent("1");
  });

  it("says there are no conditions and adds one on the first column", () => {
    const onChange = open([]);

    expect(screen.getByText("No conditions yet, so every record shows.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add condition" }));

    expect(onChange).toHaveBeenCalledWith([{ column_id: "name", op: "contains", value: null }]);
  });

  it("cannot add a condition to a table with no live column", () => {
    open([], vi.fn(), []);
    expect(screen.getByRole("button", { name: "Add condition" })).toBeDisabled();
  });

  it("starts a condition over when its column changes", async () => {
    const onChange = open([{ column_id: "name", op: "contains", value: "a" }]);

    await pick(screen.getByRole("combobox", { name: "Column" }), "Seats");

    expect(onChange).toHaveBeenCalledWith([{ column_id: "seats", op: "eq", value: null }]);
  });

  it("changes the operator, naming a date's in its own words", async () => {
    const onChange = open([{ column_id: "due", op: "eq", value: "2026-01-01" }]);

    await pick(screen.getByRole("combobox", { name: "Operator" }), "on or after");

    expect(onChange).toHaveBeenCalledWith([{ column_id: "due", op: "gte", value: "2026-01-01" }]);
  });

  it("writes a typed operand once the field is left", () => {
    const onChange = open([{ column_id: "seats", op: "gt", value: null }]);
    const input = screen.getByRole("spinbutton");

    fireEvent.change(input, { target: { value: "12" } });
    fireEvent.blur(input);

    expect(onChange).toHaveBeenCalledWith([{ column_id: "seats", op: "gt", value: 12 }]);
  });

  it("asks a yes/no condition for yes or no", async () => {
    const onChange = open([{ column_id: "paid", op: "eq", value: true }]);

    await pick(screen.getByRole("combobox", { name: "Paid" }), "False");

    expect(onChange).toHaveBeenCalledWith([{ column_id: "paid", op: "eq", value: false }]);
  });

  it("asks is any of for several options, and a multi-select's contains for one", async () => {
    const onChange = open([
      { column_id: "tier", op: "in", value: ["free"] },
      { column_id: "tags", op: "contains", value: null },
    ]);

    fireEvent.click(screen.getByRole("button", { name: /free/i }));
    fireEvent.click(await screen.findByRole("checkbox", { name: "Team" }));
    expect(onChange).toHaveBeenCalledWith([
      { column_id: "tier", op: "in", value: ["free", "team"] },
      { column_id: "tags", op: "contains", value: null },
    ]);

    const selects = screen.getAllByRole("combobox");
    await pick(selects[selects.length - 1] as HTMLElement, "Rush");
    expect(onChange).toHaveBeenLastCalledWith([
      { column_id: "tier", op: "in", value: ["free"] },
      { column_id: "tags", op: "contains", value: "rush" },
    ]);
  });

  it("asks nothing more of is empty, and treats a missing list as none chosen", () => {
    open([
      { column_id: "name", op: "is_null", value: true },
      { column_id: "tier", op: "in" },
    ]);

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText("None selected")).toBeInTheDocument();
    expect(screen.getByText("and")).toBeInTheDocument();
  });

  it("removes one condition, or all of them", () => {
    const filters: RecordFilter[] = [
      { column_id: "name", op: "contains", value: "a" },
      { column_id: "seats", op: "gt", value: 1 },
    ];
    const onChange = open(filters);

    fireEvent.click(screen.getAllByRole("button", { name: "Remove condition" })[0] as HTMLElement);
    expect(onChange).toHaveBeenCalledWith([filters[1]]);

    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("shows no row for a condition on a column that is no longer live", () => {
    open([{ column_id: "gone", op: "eq", value: "x" }]);

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("combobox")).not.toBeInTheDocument();
  });
});
