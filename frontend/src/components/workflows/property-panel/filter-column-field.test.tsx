import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { FilterColumnField } from "./filter-column-field";

const useWorkflowTableMock = vi.fn();

vi.mock("@/hooks", () => ({
  useWorkflowTable: (id: string | null) => useWorkflowTableMock(id),
}));

beforeEach(() => {
  useWorkflowTableMock.mockReturnValue({
    table: { columns: [{ id: "c1", label: "Email", type: "text", archived: false }] },
  });
});

it("names the chosen column rather than its id", () => {
  render(<FilterColumnField id="f" tableId="t1" value="c1" onChange={vi.fn()} />);
  expect(screen.getByRole("combobox", { name: "Column" })).toHaveTextContent("Email");
});

it("offers nothing while the table's columns are still unknown", () => {
  useWorkflowTableMock.mockReturnValue({ table: null });
  render(<FilterColumnField id="f" tableId="t1" value={undefined} onChange={vi.fn()} />);
  const select = screen.getByRole("combobox", { name: "Column" });
  expect(select).toBeDisabled();
  expect(select).toHaveTextContent("Choose a column");
});
