import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { CheckDraft } from "./case-form";
import { KeysValue } from "./keys-value";

const CHECK: CheckDraft = {
  type: "keys",
  value: "",
  rest: { family: "invoice", keys: [{ key: "Invoice", value: "INV-7" }] },
};

function shown(check: CheckDraft = CHECK, disabled = false) {
  const onChange = vi.fn();
  render(<KeysValue check={check} number={2} disabled={disabled} onChange={onChange} />);
  return onChange;
}

describe("KeysValue", () => {
  it("shows each fact as a label and a value", () => {
    shown();
    expect(screen.getByRole("textbox", { name: "Key 1 of check 2" })).toHaveValue("Invoice");
    expect(screen.getByRole("textbox", { name: "Value of key 1 of check 2" })).toHaveValue("INV-7");
  });

  it("adds an empty row and keeps the check's other fields", async () => {
    const onChange = shown();
    await userEvent.click(screen.getByRole("button", { name: "Add key" }));
    expect(onChange).toHaveBeenCalledWith({
      rest: {
        family: "invoice",
        keys: [
          { key: "Invoice", value: "INV-7" },
          { key: "", value: "" },
        ],
      },
    });
  });

  it("edits a label or a value in place", () => {
    const onChange = shown();
    fireEvent.change(screen.getByRole("textbox", { name: "Value of key 1 of check 2" }), {
      target: { value: "INV-8" },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      rest: { family: "invoice", keys: [{ key: "Invoice", value: "INV-8" }] },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Key 1 of check 2" }), {
      target: { value: "Invoice number" },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      rest: { family: "invoice", keys: [{ key: "Invoice number", value: "INV-7" }] },
    });
  });

  it("removes a row", async () => {
    const onChange = shown();
    await userEvent.click(screen.getByRole("button", { name: "Remove key 1 of check 2" }));
    expect(onChange).toHaveBeenCalledWith({ rest: { family: "invoice", keys: [] } });
  });

  it("changes nothing while disabled", () => {
    shown(CHECK, true);
    expect(screen.getByRole("button", { name: "Add key" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Key 1 of check 2" })).toBeDisabled();
  });
});
