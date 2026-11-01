import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ColumnDef } from "@/types/tables";
import { OptionChip, selectChips } from "./option-chip";
vi.mock("@/hooks/use-table-principals", () => ({
  useTablePrincipals: () => ({
    items: [
      { kind: "user", id: "ada", name: "Ada" },
      { kind: "agent", id: "writer", name: "Writer" },
    ],
    isLoading: false,
    error: null,
  }),
}));
const base: ColumnDef = {
  id: "status",
  label: "Status",
  type: "single_select",
  nullable: true,
  default: null,
  archived: false,
  options: [{ id: "open", label: "Open", color: "blue", archived: true }],
};
it("retains configured colors and visibly retires archived choices", () => {
  render(<OptionChip column={base} optionId="open" />);
  expect(screen.getByText("Open")).toHaveClass("line-through", "text-sky-700");
});
it("renders unknown and multi-select values without inventing an option", () => {
  render(<>{selectChips({ ...base, type: "multi_select" }, ["open", 4, "unknown"])}</>);
  expect(screen.getByText("unknown")).toBeVisible();
  expect(screen.queryByText("4")).toBeNull();
  expect(selectChips({ ...base, type: "text" }, "open")).toBeNull();
});
it.each(["user", "multi_user", "agent", "multi_agent"] as const)(
  "renders %s identities as names",
  (type) => {
    const value = type.includes("user") ? "ada" : "writer";
    render(<>{selectChips({ ...base, type }, type.startsWith("multi") ? [value] : value)}</>);
    expect(screen.getByText(value === "ada" ? "Ada" : "Writer")).toBeVisible();
  },
);
