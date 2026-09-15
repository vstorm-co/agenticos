import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ChipsInput } from "./chips-input";

/**
 * The chips editor: type a value, commit it as a removable chip.
 *
 * A controlled component, so the tests drive it through a stateful harness -
 * asserting on the values it hands back and on the accessible names it exposes,
 * which is what a reader (and a screen reader) actually meets.
 */
function Harness({
  initial = [],
  disabled = false,
  maxItems = 5,
  maxLength = 32,
  onChange,
}: {
  initial?: string[];
  disabled?: boolean;
  maxItems?: number;
  maxLength?: number;
  onChange?: (values: string[]) => void;
}) {
  const [values, setValues] = useState(initial);
  return (
    <ChipsInput
      values={values}
      onChange={(next) => {
        setValues(next);
        onChange?.(next);
      }}
      inputLabel="Add a tag"
      removeLabel={(value) => `Remove ${value}`}
      placeholder="Add a tag"
      maxItems={maxItems}
      maxLength={maxLength}
      disabled={disabled}
    />
  );
}

function box() {
  return screen.getByRole("textbox", { name: "Add a tag" });
}

describe("ChipsInput", () => {
  it("commits a value on Enter", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    await userEvent.type(box(), "sales{Enter}");

    expect(onChange).toHaveBeenLastCalledWith(["sales"]);
    expect(screen.getByText("sales")).toBeInTheDocument();
  });

  it("commits a value on blur", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    await userEvent.type(box(), "urgent");
    await userEvent.tab();

    expect(onChange).toHaveBeenLastCalledWith(["urgent"]);
  });

  it("ignores a blank value rather than adding an empty chip", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    await userEvent.type(box(), "   {Enter}");

    expect(onChange).not.toHaveBeenCalled();
  });

  it("drops a duplicate on the client, though the server does the canonical fold", async () => {
    const onChange = vi.fn();
    render(<Harness initial={["sales"]} onChange={onChange} />);

    await userEvent.type(box(), "sales{Enter}");

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getAllByText("sales")).toHaveLength(1);
  });

  it("removes a chip from its ✕", async () => {
    const onChange = vi.fn();
    render(<Harness initial={["sales", "urgent"]} onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "Remove sales" }));

    expect(onChange).toHaveBeenLastCalledWith(["urgent"]);
  });

  it("removes the last chip on Backspace when the box is empty", async () => {
    const onChange = vi.fn();
    render(<Harness initial={["sales", "urgent"]} onChange={onChange} />);

    await userEvent.type(box(), "{Backspace}");

    expect(onChange).toHaveBeenLastCalledWith(["sales"]);
  });

  it("does nothing on Backspace when there is neither a draft nor a chip", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    await userEvent.type(box(), "{Backspace}");

    expect(onChange).not.toHaveBeenCalled();
  });

  it("leaves the draft alone when Backspace has text to delete", async () => {
    const onChange = vi.fn();
    render(<Harness initial={["sales"]} onChange={onChange} />);

    // A Backspace with a draft present deletes a character rather than a chip.
    await userEvent.type(box(), "ab{Backspace}");

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText("sales")).toBeInTheDocument();
  });

  it("disables adding once the count cap is reached", () => {
    render(<Harness initial={["a", "b"]} maxItems={2} />);

    expect(box()).toBeDisabled();
  });

  it("keeps adding possible below the cap", () => {
    render(<Harness initial={["a"]} maxItems={2} />);

    expect(box()).toBeEnabled();
  });

  it("disables the whole control, chips and box, while a save is in flight", () => {
    render(<Harness initial={["sales"]} disabled />);

    expect(box()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove sales" })).toBeDisabled();
  });
});
