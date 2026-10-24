import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AddColumnDialog, RenameColumnDialog, currentColumns } from "./column-dialogs";

const hooks = vi.hoisted(() => ({
  tables: [] as { id: string; name: string }[],
  linked: null as { columns: ColumnDef[] } | null,
  asked: [] as (string | null)[],
  error: null as Error | null,
  refetch: vi.fn(),
}));

vi.mock("@/hooks", () => ({
  useAllTables: () => ({ tables: hooks.tables, error: hooks.error, refetch: hooks.refetch }),
  useTable: (tableId: string | null) => {
    hooks.asked.push(tableId);
    return { table: tableId ? hooks.linked : undefined };
  },
}));
import type { ColumnDef } from "@/types/tables";

const tier: ColumnDef = {
  id: "c1",
  label: "Tier",
  type: "single_select",
  nullable: false,
  default: "o1",
  options: [{ id: "o1", label: "Free", archived: false }],
  archived: false,
};

describe("currentColumns", () => {
  it("submits every column as the table has it, archived ones included", () => {
    expect(currentColumns([tier, { ...tier, id: "c2", archived: true }])).toEqual([
      {
        id: "c1",
        label: "Tier",
        type: "single_select",
        nullable: false,
        default: "o1",
        options: [{ id: "o1", label: "Free", archived: false }],
        archived: false,
        link_table_id: null,
        link_column_id: null,
        target_column_id: null,
        aggregate: null,
        formula: null,
      },
      expect.objectContaining({ id: "c2", archived: true }),
    ]);
  });
});

describe("RenameColumnDialog", () => {
  it("starts from the column's label and renames it once it differs", async () => {
    const user = userEvent.setup();
    const onRename = vi.fn();
    const { rerender } = render(
      <RenameColumnDialog
        column={null}
        onOpenChange={vi.fn()}
        onRename={onRename}
        isSaving={false}
      />,
    );
    rerender(
      <RenameColumnDialog
        column={tier}
        onOpenChange={vi.fn()}
        onRename={onRename}
        isSaving={false}
      />,
    );
    const input = screen.getByLabelText("Name");
    expect(input).toHaveValue("Tier");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    await user.clear(input);
    await user.type(input, "  Plan ");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(onRename).toHaveBeenCalledWith(tier, "Plan");
  });

  it("refuses a blank name, even from Enter", () => {
    const onRename = vi.fn();
    render(
      <RenameColumnDialog
        column={tier}
        onOpenChange={vi.fn()}
        onRename={onRename}
        isSaving={false}
      />,
    );
    const input = screen.getByLabelText("Name");

    fireEvent.change(input, { target: { value: "  " } });
    fireEvent.submit(input);

    expect(onRename).not.toHaveBeenCalled();
  });

  it("closes from Cancel", async () => {
    const onOpenChange = vi.fn();
    render(
      <RenameColumnDialog
        column={tier}
        onOpenChange={onOpenChange}
        onRename={vi.fn()}
        isSaving={false}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe("AddColumnDialog", () => {
  it("adds an optional column of the chosen type", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();
    render(
      <AddColumnDialog open columns={[]} onOpenChange={vi.fn()} onAdd={onAdd} isSaving={false} />,
    );

    await user.type(screen.getByLabelText("Name"), " Notes ");
    await user.click(screen.getByRole("combobox", { name: "Type" }));
    await user.click(screen.getByRole("option", { name: "Long text" }));
    await user.click(screen.getByRole("button", { name: "Add column" }));

    expect(onAdd).toHaveBeenCalledWith({
      label: "Notes",
      type: "long_text",
      nullable: true,
      options: [],
    });
  });

  it("asks a select for its options, one per line, each once", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();
    render(
      <AddColumnDialog open columns={[]} onOpenChange={vi.fn()} onAdd={onAdd} isSaving={false} />,
    );

    await user.type(screen.getByLabelText("Name"), "Region");
    await user.click(screen.getByRole("combobox", { name: "Type" }));
    await user.click(screen.getByRole("option", { name: "Multi select" }));
    const add = screen.getByRole("button", { name: "Add column" });
    expect(add).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Options"), {
      target: { value: "EMEA\n\n APAC \nEMEA" },
    });
    await user.click(add);

    expect(onAdd).toHaveBeenCalledWith({
      label: "Region",
      type: "multi_select",
      nullable: true,
      options: [{ label: "EMEA" }, { label: "APAC" }],
    });
  });

  it("refuses to submit without a name, and forgets the form once closed", () => {
    const onAdd = vi.fn();
    const onOpenChange = vi.fn();
    const { rerender } = render(
      <AddColumnDialog
        open
        columns={[]}
        onOpenChange={onOpenChange}
        onAdd={onAdd}
        isSaving={false}
      />,
    );
    fireEvent.submit(screen.getByLabelText("Name"));
    expect(onAdd).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    rerender(
      <AddColumnDialog
        open={false}
        columns={[]}
        onOpenChange={onOpenChange}
        onAdd={onAdd}
        isSaving={false}
      />,
    );
    rerender(
      <AddColumnDialog
        open
        columns={[]}
        onOpenChange={onOpenChange}
        onAdd={onAdd}
        isSaving={false}
      />,
    );

    expect(screen.getByLabelText("Name")).toHaveValue("");
  });

  it("links a column to a table the member chooses", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();
    hooks.tables = [
      ...Array.from({ length: 100 }, (_, i) => ({ id: `t-${i}`, name: `Table ${i}` })),
      { id: "t-products", name: "Products" },
    ];
    render(
      <AddColumnDialog open columns={[]} onOpenChange={vi.fn()} onAdd={onAdd} isSaving={false} />,
    );

    await user.type(screen.getByLabelText("Name"), "Items");
    await user.click(screen.getByRole("combobox", { name: "Type" }));
    await user.click(screen.getByRole("option", { name: "Link" }));
    const add = screen.getByRole("button", { name: "Add column" });
    expect(add).toBeDisabled();
    await user.click(screen.getByRole("combobox", { name: "Links to" }));
    await user.click(screen.getByRole("option", { name: "Products" }));
    await user.click(add);

    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({ label: "Items", type: "link", link_table_id: "t-products" }),
    );
  });

  it("says a lookup needs a link column before it can read through one", async () => {
    const user = userEvent.setup();
    render(
      <AddColumnDialog
        open
        columns={[tier]}
        onOpenChange={vi.fn()}
        onAdd={vi.fn()}
        isSaving={false}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Type" }));
    await user.click(screen.getByRole("option", { name: "Lookup" }));

    expect(screen.getByText(/Add a link column first/)).toBeVisible();
  });

  const items: ColumnDef = {
    ...tier,
    id: "c-items",
    label: "Items",
    type: "link",
    link_table_id: "t-products",
  };
  const product = (id: string, label: string, type: ColumnDef["type"]): ColumnDef => ({
    ...tier,
    id,
    label,
    type,
    options: [],
  });

  it("reads one column of the linked table through a link, offering only columns that hold values", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();
    hooks.linked = {
      columns: [
        product("p-name", "Name", "text"),
        product("p-other", "Other link", "link"),
        { ...product("p-old", "Old", "text"), archived: true },
      ],
    };
    render(
      <AddColumnDialog
        open
        columns={[items]}
        onOpenChange={vi.fn()}
        onAdd={onAdd}
        isSaving={false}
      />,
    );

    await user.type(screen.getByLabelText("Name"), "Names");
    await user.click(screen.getByRole("combobox", { name: "Type" }));
    await user.click(screen.getByRole("option", { name: "Lookup" }));
    await user.click(screen.getByRole("combobox", { name: "Through the link" }));
    await user.click(screen.getByRole("option", { name: "Items" }));
    expect(hooks.asked).toContain("t-products");
    await user.click(screen.getByRole("combobox", { name: "Reads" }));
    expect(screen.queryByRole("option", { name: "Other link" })).toBeNull();
    expect(screen.queryByRole("option", { name: "Old" })).toBeNull();
    await user.click(screen.getByRole("option", { name: "Name" }));
    await user.click(screen.getByRole("button", { name: "Add column" }));

    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "lookup",
        link_column_id: "c-items",
        target_column_id: "p-name",
      }),
    );
  });

  it("rolls up a count with no column, and a sum only over numbers", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();
    hooks.linked = {
      columns: [product("p-name", "Name", "text"), product("p-price", "Price", "number")],
    };
    render(
      <AddColumnDialog
        open
        columns={[items]}
        onOpenChange={vi.fn()}
        onAdd={onAdd}
        isSaving={false}
      />,
    );

    await user.type(screen.getByLabelText("Name"), "Count");
    await user.click(screen.getByRole("combobox", { name: "Type" }));
    await user.click(screen.getByRole("option", { name: "Rollup" }));
    await user.click(screen.getByRole("combobox", { name: "Through the link" }));
    await user.click(screen.getByRole("option", { name: "Items" }));
    expect(screen.queryByRole("combobox", { name: "Reads" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Add column" }));
    expect(onAdd).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "rollup", aggregate: "count", target_column_id: null }),
    );

    await user.click(screen.getByRole("combobox", { name: "Works out" }));
    await user.click(screen.getByRole("option", { name: "Sum" }));
    const add = screen.getByRole("button", { name: "Add column" });
    expect(add).toBeDisabled();
    await user.click(screen.getByRole("combobox", { name: "Reads" }));
    expect(screen.queryByRole("option", { name: "Name" })).toBeNull();
    await user.click(screen.getByRole("option", { name: "Price" }));
    await user.click(add);
    expect(onAdd).toHaveBeenLastCalledWith(
      expect.objectContaining({ aggregate: "sum", target_column_id: "p-price" }),
    );
  });

  it("lets a minimum read dates as well as numbers", async () => {
    const user = userEvent.setup();
    hooks.linked = {
      columns: [product("p-due", "Due", "date"), product("p-name", "Name", "text")],
    };
    render(
      <AddColumnDialog
        open
        columns={[items]}
        onOpenChange={vi.fn()}
        onAdd={vi.fn()}
        isSaving={false}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Type" }));
    await user.click(screen.getByRole("option", { name: "Rollup" }));
    await user.click(screen.getByRole("combobox", { name: "Through the link" }));
    await user.click(screen.getByRole("option", { name: "Items" }));
    await user.click(screen.getByRole("combobox", { name: "Works out" }));
    await user.click(screen.getByRole("option", { name: "Smallest" }));
    await user.click(screen.getByRole("combobox", { name: "Reads" }));

    expect(screen.getByRole("option", { name: "Due" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Name" })).toBeNull();
  });

  it("adds a formula column with the formula written", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();
    render(
      <AddColumnDialog
        open
        columns={[{ ...tier, id: "c-price", label: "Price", type: "number", options: [] }]}
        onOpenChange={vi.fn()}
        onAdd={onAdd}
        isSaving={false}
      />,
    );

    await user.type(screen.getByLabelText("Name"), "Gross");
    await user.click(screen.getByRole("combobox", { name: "Type" }));
    await user.click(screen.getByRole("option", { name: "Formula" }));
    const add = screen.getByRole("button", { name: "Add column" });
    expect(add).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Price" }));
    await user.type(screen.getByLabelText("Formula"), " * 1.23");
    await user.click(add);

    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({ type: "formula", formula: "{Price} * 1.23" }),
    );
  });
});

it("retries a failed link-table catalog without losing the column form", async () => {
  hooks.error = new Error("offline");
  try {
    render(
      <AddColumnDialog
        open
        columns={[tier]}
        onOpenChange={vi.fn()}
        onAdd={vi.fn()}
        isSaving={false}
      />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Type" }));
    await userEvent.click(screen.getByRole("option", { name: "Link" }));
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(hooks.refetch).toHaveBeenCalledOnce();
    expect(screen.getByLabelText("Name")).toBeVisible();
  } finally {
    hooks.error = null;
    hooks.refetch.mockClear();
  }
});
