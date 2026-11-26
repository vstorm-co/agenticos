import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FilterValueField } from "./filter-value-field";

const useWorkflowTableMock = vi.fn();

vi.mock("@/hooks", () => ({
  useWorkflowTable: (id: string | null) => useWorkflowTableMock(id),
}));

const option = (id: string, label: string, archived = false) => ({ id, label, archived });

beforeEach(() => {
  useWorkflowTableMock.mockReturnValue({
    table: {
      columns: [
        { id: "email", label: "Email", type: "text", archived: false, options: [] },
        {
          id: "status",
          label: "Status",
          type: "single_select",
          archived: false,
          options: [
            option("o1", "Worth sharing"),
            option("o2", "Not worth sharing"),
            option("o3", "Old", true),
          ],
        },
        {
          id: "tags",
          label: "Tags",
          type: "multi_select",
          archived: false,
          options: [option("t1", "AI")],
        },
      ],
    },
  });
});

function mount(props: { columnId: unknown; op: unknown; value?: unknown; error?: string }) {
  const onChange = vi.fn();
  render(
    <FilterValueField
      id="v"
      tableId="table-id"
      fallback={<span>typed value</span>}
      onChange={onChange}
      value={props.value}
      columnId={props.columnId}
      op={props.op}
      error={props.error}
    />,
  );
  return onChange;
}

describe("FilterValueField", () => {
  it.each([
    ["a column with no options", "email", "eq"],
    ["an emptiness test", "status", "is_null"],
    ["a column not chosen yet", undefined, "eq"],
  ])("keeps the typed value for %s", (_, columnId, op) => {
    mount({ columnId, op });
    expect(screen.getByText("typed value")).toBeInTheDocument();
  });

  it("offers a single select's live options and saves the chosen option's id", async () => {
    const onChange = mount({ columnId: "status", op: "eq", error: "Pick one" });

    expect(screen.getByRole("combobox", { name: "Value" })).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("combobox", { name: "Value" })).toHaveAccessibleDescription("Pick one");
    await userEvent.click(screen.getByRole("combobox", { name: "Value" }));
    expect(screen.queryByRole("option", { name: "Old" })).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: "Not worth sharing" }));

    expect(onChange).toHaveBeenLastCalledWith("o2");
  });

  it("names a chosen option by its label", () => {
    mount({ columnId: "tags", op: "contains", value: "t1" });
    expect(screen.getByRole("combobox", { name: "Value" })).toHaveTextContent("AI");
  });

  it("chooses several options for in, and clears the value when none is left", async () => {
    const onChange = mount({ columnId: "status", op: "in", value: ["o1"], error: "Too few" });

    expect(screen.getByText("Too few")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: "Not worth sharing" }));
    expect(onChange).toHaveBeenLastCalledWith(["o1", "o2"]);
    await userEvent.click(screen.getByRole("checkbox", { name: "Worth sharing" }));
    expect(onChange).toHaveBeenLastCalledWith(undefined);
  });

  it("starts an in list from nothing", async () => {
    const onChange = mount({ columnId: "status", op: "in" });
    await userEvent.click(screen.getByRole("checkbox", { name: "Worth sharing" }));
    expect(onChange).toHaveBeenLastCalledWith(["o1"]);
  });

  it("shows an option stored by its label as that option, and saves an id from then on", async () => {
    const onChange = mount({ columnId: "status", op: "in", value: [" worth SHARING", "o2"] });

    expect(screen.getByRole("checkbox", { name: "Worth sharing" })).toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: "Not worth sharing" }));
    expect(onChange).toHaveBeenLastCalledWith(["o1"]);
  });

  it("keeps a chosen option archived since listed, so it can be removed", async () => {
    const onChange = mount({ columnId: "status", op: "in", value: ["o1", "o3"] });

    const archived = screen.getByRole("checkbox", { name: "Old (archived)" });
    expect(archived).toBeChecked();
    await userEvent.click(archived);
    expect(onChange).toHaveBeenLastCalledWith(["o1"]);
  });

  it("shows a single choice archived since by its label", () => {
    mount({ columnId: "status", op: "ne", value: "o3" });
    expect(screen.getByRole("combobox", { name: "Value" })).toHaveTextContent("Old (archived)");
  });

  it.each([
    ["a single operand", "eq", "Nonsense"],
    ["a list", "in", ["o1", "Nonsense"]],
    ["a number", "eq", 3],
    ["zero", "eq", 0],
    ["false", "eq", false],
    ["a malformed list", "in", "o1"],
  ])("keeps the typed value when %s names no option", (_, op, value) => {
    mount({ columnId: "status", op, value });
    expect(screen.getByText("typed value")).toBeInTheDocument();
  });

  it("keeps the typed value while the table is unknown", () => {
    useWorkflowTableMock.mockReturnValue({ table: null });
    mount({ columnId: "status", op: "eq" });
    expect(screen.getByText("typed value")).toBeInTheDocument();
  });
});
