import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { FilterColumnField } from "./filter-column-field";

const useWorkflowTableMock = vi.fn();

vi.mock("@/hooks", () => ({
  useWorkflowTable: (id: string | null) => useWorkflowTableMock(id),
}));

const EMAIL = { id: "c1", label: "Email", type: "text", archived: false };

beforeEach(() => {
  useWorkflowTableMock.mockReturnValue({
    table: {
      columns: [
        EMAIL,
        { id: "c2", label: "Total", type: "formula", archived: false },
        { id: "c3", label: "Retired", type: "text", archived: true },
      ],
    },
  });
});

it("names the chosen column rather than its id", () => {
  render(<FilterColumnField id="f" tableId="t1" value="c1" onPick={vi.fn()} />);
  expect(screen.getByRole("combobox", { name: "Column" })).toHaveTextContent("Email");
});

it("offers only live columns a filter can test, and hands back the whole column", async () => {
  const onPick = vi.fn();
  render(<FilterColumnField id="f" tableId="t1" value={undefined} onPick={onPick} />);

  await userEvent.click(screen.getByRole("combobox", { name: "Column" }));
  expect(screen.queryByRole("option", { name: "Total" })).toBeNull();
  expect(screen.queryByRole("option", { name: "Retired" })).toBeNull();
  await userEvent.click(screen.getByRole("option", { name: "Email" }));

  expect(onPick).toHaveBeenCalledWith(EMAIL);
});

it("asks for a table first, and is inert for a caller who may not edit", () => {
  const { rerender } = render(
    <FilterColumnField id="f" tableId={null} value={undefined} onPick={vi.fn()} />,
  );
  expect(screen.getByRole("combobox", { name: "Column" })).toHaveTextContent(
    "Choose a table first",
  );
  rerender(
    <FilterColumnField id="f" tableId="t1" value="c1" onPick={vi.fn()} disabled error="Gone" />,
  );
  expect(screen.getByRole("combobox", { name: "Column" })).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "Column" })).toHaveAccessibleDescription("Gone");
});

it("offers nothing while the table's columns are still unknown", () => {
  useWorkflowTableMock.mockReturnValue({ table: null });
  render(<FilterColumnField id="f" tableId="t1" value={undefined} onPick={vi.fn()} />);
  const select = screen.getByRole("combobox", { name: "Column" });
  expect(select).toBeDisabled();
  expect(select).toHaveTextContent("Choose a column");
});

it.each([
  ["c3", "Retired"],
  ["c2", "Total"],
  ["missing", "missing"],
])("keeps an unavailable saved column %s visible until replaced", (value, label) => {
  render(<FilterColumnField id="f" tableId="t1" value={value} onPick={vi.fn()} />);
  expect(screen.getByRole("combobox", { name: "Column" })).toHaveTextContent(label);
});
