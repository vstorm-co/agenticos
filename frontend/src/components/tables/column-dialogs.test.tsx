import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AddColumnDialog, RenameColumnDialog, currentColumns } from "./column-dialogs";
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
    render(<AddColumnDialog open onOpenChange={vi.fn()} onAdd={onAdd} isSaving={false} />);

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
    render(<AddColumnDialog open onOpenChange={vi.fn()} onAdd={onAdd} isSaving={false} />);

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
      <AddColumnDialog open onOpenChange={onOpenChange} onAdd={onAdd} isSaving={false} />,
    );
    fireEvent.submit(screen.getByLabelText("Name"));
    expect(onAdd).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    rerender(
      <AddColumnDialog open={false} onOpenChange={onOpenChange} onAdd={onAdd} isSaving={false} />,
    );
    rerender(<AddColumnDialog open onOpenChange={onOpenChange} onAdd={onAdd} isSaving={false} />);

    expect(screen.getByLabelText("Name")).toHaveValue("");
  });
});
