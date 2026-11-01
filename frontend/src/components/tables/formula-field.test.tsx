import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ColumnDef } from "@/types/tables";

import { FormulaField } from "./formula-field";

const col = (label: string, type: ColumnDef["type"], archived = false): ColumnDef => ({
  id: label,
  label,
  type,
  nullable: true,
  default: null,
  options: [],
  archived,
});

const columns = [
  col("Price", "number"),
  col("Quantity", "integer"),
  col("Old", "text", true),
  col("Items", "link"),
  col("Total", "formula"),
];

describe("FormulaField", () => {
  it("offers the columns a formula may read, and writes one in braces where the cursor is", () => {
    const onChange = vi.fn();
    render(<FormulaField id="f" value="1 + " columns={columns} onChange={onChange} />);

    expect(screen.queryByRole("button", { name: "Old" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Items" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Total" })).toBeNull();
    const field = screen.getByLabelText("Formula") as HTMLTextAreaElement;
    field.setSelectionRange(4, 4);
    fireEvent.click(screen.getByRole("button", { name: "Price" }));

    expect(onChange).toHaveBeenCalledWith("1 + {Price}");
  });

  it("leaves the cursor after an inserted column, so typing goes on from there", async () => {
    const user = userEvent.setup();
    function Controlled() {
      const [value, setValue] = useState("");
      return <FormulaField id="f" value={value} columns={columns} onChange={setValue} />;
    }
    render(<Controlled />);

    await user.click(screen.getByRole("button", { name: "Quantity" }));
    await user.keyboard(" * 2");

    expect(screen.getByLabelText("Formula")).toHaveValue("{Quantity} * 2");
  });

  it("types a formula as written and says what the service refused", () => {
    const onChange = vi.fn();
    render(
      <FormulaField
        id="f"
        value=""
        columns={[]}
        onChange={onChange}
        error="Not written correctly"
      />,
    );

    fireEvent.change(screen.getByLabelText("Formula"), { target: { value: "{Price} *" } });

    expect(onChange).toHaveBeenCalledWith("{Price} *");
    expect(screen.getByLabelText("Formula")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Not written correctly")).toBeVisible();
  });
});
