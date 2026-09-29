import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InlineCell } from "./inline-cell";
import type { ColumnDef } from "@/types/tables";

const name: ColumnDef = {
  id: "c1",
  label: "Name",
  type: "text",
  nullable: true,
  default: null,
  options: [],
  archived: false,
};

describe("InlineCell", () => {
  it("writes nothing from a blur that follows Escape", () => {
    const onCommit = vi.fn();
    const onDone = vi.fn();
    // `onDone` does not unmount here, so the blur a browser may send as the
    // cell closes reaches the field that was just thrown away.
    render(<InlineCell column={name} value="Ada" onCommit={onCommit} onDone={onDone} />);
    const input = screen.getByRole("textbox");

    fireEvent.change(input, { target: { value: "Grace" } });
    fireEvent.keyDown(input, { key: "Escape" });
    fireEvent.blur(input);

    expect(onDone).toHaveBeenCalled();
    expect(onCommit).not.toHaveBeenCalled();
  });
});
