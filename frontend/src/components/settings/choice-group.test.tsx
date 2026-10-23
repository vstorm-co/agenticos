import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { Radar } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { ChoiceGroup } from "./choice-group";

const OPTIONS = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Beta" },
  { value: "c", label: "Gamma" },
] as const;

type Value = (typeof OPTIONS)[number]["value"];

function Harness({ initial, onChange }: { initial?: Value; onChange?: (value: Value) => void }) {
  const [value, setValue] = useState<Value | undefined>(initial);
  return (
    <>
      {/* i18n-exempt: a test label, not copy */}
      <span id="label">Letters</span>
      <ChoiceGroup
        labelledBy="label"
        value={value}
        options={OPTIONS}
        onChange={(next) => {
          setValue(next);
          onChange?.(next);
        }}
      />
    </>
  );
}

describe("ChoiceGroup", () => {
  it("is one tab stop, on the checked choice", () => {
    render(<Harness initial="b" />);

    expect(screen.getByRole("radiogroup", { name: "Letters" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Beta" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("radio", { name: "Alpha" })).toHaveAttribute("tabindex", "-1");
  });

  it("puts the tab stop on the first choice while none is checked", () => {
    render(<Harness />);

    expect(screen.getByRole("radio", { name: "Alpha" })).toHaveAttribute("tabindex", "0");
  });

  it("moves and selects with the arrow keys, wrapping at both ends", async () => {
    const onChange = vi.fn();
    render(<Harness initial="c" onChange={onChange} />);
    screen.getByRole("radio", { name: "Gamma" }).focus();

    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "Alpha" })).toHaveFocus();
    expect(screen.getByRole("radio", { name: "Alpha" })).toBeChecked();

    await userEvent.keyboard("{ArrowUp}");
    expect(screen.getByRole("radio", { name: "Gamma" })).toHaveFocus();

    await userEvent.keyboard("{ArrowLeft}{ArrowDown}");
    expect(onChange).toHaveBeenLastCalledWith("c");
  });

  it("ignores every other key", async () => {
    const onChange = vi.fn();
    render(<Harness initial="a" onChange={onChange} />);
    screen.getByRole("radio", { name: "Alpha" }).focus();

    await userEvent.keyboard("x");

    expect(onChange).not.toHaveBeenCalled();
  });

  it("draws a choice's icon beside its label, out of its accessible name", () => {
    render(
      <ChoiceGroup
        labelledBy="none"
        value="w"
        options={[{ value: "w", label: "Watches", icon: Radar }]}
        onChange={vi.fn()}
      />,
    );
    const choice = screen.getByRole("radio", { name: "Watches" });
    expect(choice.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});
