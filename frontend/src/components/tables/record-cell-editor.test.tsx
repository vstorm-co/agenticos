import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RecordCellEditor } from "./record-cell-editor";
import type { ColumnDef } from "@/types/tables";

function column(overrides: Partial<ColumnDef>): ColumnDef {
  return {
    id: "c1",
    label: "Column",
    type: "text",
    nullable: true,
    default: null,
    options: [],
    archived: false,
    ...overrides,
  };
}

describe("RecordCellEditor", () => {
  it("renders a text control and reports the edited text", () => {
    const onChange = vi.fn();
    render(<RecordCellEditor column={column({ type: "text" })} value="" onChange={onChange} />);

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "hi" } });

    expect(onChange).toHaveBeenLastCalledWith("hi");
  });

  it("renders a text control with a non-string stored value as empty", () => {
    render(<RecordCellEditor column={column({ type: "text" })} value={null} onChange={vi.fn()} />);
    expect(screen.getByRole("textbox")).toHaveValue("");
  });

  it("renders a long_text control as a textarea and reports the edited text", () => {
    const onChange = vi.fn();
    render(
      <RecordCellEditor column={column({ type: "long_text" })} value="story" onChange={onChange} />,
    );
    const textarea = screen.getByRole("textbox");
    expect(textarea).toHaveValue("story");

    fireEvent.change(textarea, { target: { value: "a longer story" } });

    expect(onChange).toHaveBeenLastCalledWith("a longer story");
  });

  it("renders a long_text control with a non-string stored value as empty", () => {
    render(
      <RecordCellEditor column={column({ type: "long_text" })} value={null} onChange={vi.fn()} />,
    );
    expect(screen.getByRole("textbox")).toHaveValue("");
  });

  it("renders a number control and reports a parsed float, or null when cleared", () => {
    const onChange = vi.fn();
    render(
      <RecordCellEditor column={column({ type: "number" })} value={1.5} onChange={onChange} />,
    );
    const input = screen.getByRole("spinbutton");

    fireEvent.change(input, { target: { value: "3.25" } });
    expect(onChange).toHaveBeenLastCalledWith(3.25);

    fireEvent.change(input, { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("renders a number control with a non-number stored value as empty", () => {
    render(
      <RecordCellEditor column={column({ type: "number" })} value={null} onChange={vi.fn()} />,
    );
    expect(screen.getByRole("spinbutton")).toHaveValue(null);
  });

  it("renders an integer control and truncates a fractional entry", () => {
    const onChange = vi.fn();
    render(
      <RecordCellEditor column={column({ type: "integer" })} value={null} onChange={onChange} />,
    );
    const input = screen.getByRole("spinbutton");

    fireEvent.change(input, { target: { value: "7.9" } });

    expect(onChange).toHaveBeenLastCalledWith(7);
  });

  it("renders an integer control with a stored number value", () => {
    render(<RecordCellEditor column={column({ type: "integer" })} value={4} onChange={vi.fn()} />);
    expect(screen.getByRole("spinbutton")).toHaveValue(4);
  });

  it("renders an integer control with a non-number stored value as empty", () => {
    render(
      <RecordCellEditor column={column({ type: "integer" })} value={null} onChange={vi.fn()} />,
    );
    expect(screen.getByRole("spinbutton")).toHaveValue(null);
  });

  it("renders a Switch for a non-nullable boolean column", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <RecordCellEditor
        column={column({ type: "boolean", nullable: false })}
        value={false}
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole("switch"));

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("renders a tri-state Select for a nullable boolean column", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <RecordCellEditor
        column={column({ type: "boolean", nullable: true })}
        value={null}
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByText("True"));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("a nullable boolean stored as false selects the False option", () => {
    render(
      <RecordCellEditor
        column={column({ type: "boolean", nullable: true })}
        value={false}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("combobox")).toHaveTextContent("False");
  });

  it("clearing the nullable boolean select reports null", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <RecordCellEditor
        column={column({ type: "boolean", nullable: true })}
        value={true}
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByText("Not set"));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("renders a date control and reports an edited date", () => {
    const onChange = vi.fn();
    render(
      <RecordCellEditor column={column({ type: "date" })} value="2026-09-23" onChange={onChange} />,
    );
    const input = document.querySelector('input[type="date"]') as HTMLInputElement;
    expect(input).toHaveValue("2026-09-23");

    fireEvent.change(input, { target: { value: "2026-10-01" } });

    expect(onChange).toHaveBeenCalledWith("2026-10-01");
  });

  it("renders a date control with a non-string stored value as empty", () => {
    render(<RecordCellEditor column={column({ type: "date" })} value={5} onChange={vi.fn()} />);
    expect(document.querySelector('input[type="date"]')).toHaveValue("");
  });

  it("renders a datetime control and reports a converted value on blur", () => {
    const onChange = vi.fn();
    render(
      <RecordCellEditor
        column={column({ type: "datetime" })}
        value="2026-09-23T10:00:00Z"
        onChange={onChange}
      />,
    );
    const input = document.querySelector('input[type="datetime-local"]') as HTMLInputElement;
    expect(input).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "2026-09-23T11:00" } });
    fireEvent.blur(input);

    expect(onChange).toHaveBeenCalled();
  });

  it("renders a datetime control with a non-string stored value as empty", () => {
    render(<RecordCellEditor column={column({ type: "datetime" })} value={5} onChange={vi.fn()} />);
    expect(document.querySelector('input[type="datetime-local"]')).toHaveValue("");
  });

  it("renders single_select options, keyed on id, with archived ones struck through", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    const col = column({
      type: "single_select",
      options: [
        { id: "o1", label: "Open", archived: false },
        { id: "o2", label: "Closed", archived: true },
      ],
    });
    // The record holds the archived option - it still renders, read-only in spirit.
    render(<RecordCellEditor column={col} value="o2" onChange={onChange} />);

    await user.click(screen.getByRole("combobox"));
    const listbox = screen.getByRole("listbox");
    expect(within(listbox).getByRole("option", { name: "Closed" })).toBeInTheDocument();
    await user.click(within(listbox).getByRole("option", { name: "Open" }));

    expect(onChange).toHaveBeenCalledWith("o1");
  });

  it("an archived option not currently held is not offered", async () => {
    const user = userEvent.setup();
    const col = column({
      type: "single_select",
      options: [
        { id: "o1", label: "Open", archived: false },
        { id: "o2", label: "Closed", archived: true },
      ],
    });
    render(<RecordCellEditor column={col} value="o1" onChange={vi.fn()} />);

    await user.click(screen.getByRole("combobox"));

    expect(screen.queryByText("Closed")).not.toBeInTheDocument();
  });

  it("a single_select with a non-string stored value shows Not set", () => {
    const col = column({
      type: "single_select",
      options: [{ id: "o1", label: "Open", archived: false }],
    });
    render(<RecordCellEditor column={col} value={null} onChange={vi.fn()} />);
    expect(screen.getByRole("combobox")).toHaveTextContent(/not set/i);
  });

  it("clearing single_select reports null", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    const col = column({
      type: "single_select",
      options: [{ id: "o1", label: "Open", archived: false }],
    });
    render(<RecordCellEditor column={col} value="o1" onChange={onChange} />);

    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByText("Not set"));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("renders a multi_select control", () => {
    const col = column({
      type: "multi_select",
      options: [{ id: "o1", label: "Rush", archived: false }],
    });
    render(<RecordCellEditor column={col} value={["o1"]} onChange={vi.fn()} />);
    expect(screen.getByText("Rush")).toBeInTheDocument();
  });

  it("renders a multi_select control with a non-array stored value as none selected", () => {
    const col = column({
      type: "multi_select",
      options: [{ id: "o1", label: "Rush", archived: false }],
    });
    render(<RecordCellEditor column={col} value={null} onChange={vi.fn()} />);
    expect(screen.getByText(/none selected/i)).toBeInTheDocument();
  });

  it("shows an inline error beside the control", () => {
    render(
      <RecordCellEditor
        column={column({ type: "text" })}
        value=""
        onChange={vi.fn()}
        error="This column is required"
      />,
    );
    expect(screen.getByText("This column is required")).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveAttribute("aria-invalid", "true");
  });

  it("disables the control when asked", () => {
    render(
      <RecordCellEditor column={column({ type: "text" })} value="" onChange={vi.fn()} disabled />,
    );
    expect(screen.getByRole("textbox")).toBeDisabled();
  });
});
