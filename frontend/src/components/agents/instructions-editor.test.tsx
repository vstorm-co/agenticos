import { fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { InstructionsEditor } from "./instructions-editor";

const VARIABLES = [
  { name: "user_name", description: "The signed-in person's name" },
  { name: "current_time", description: "The time" },
];

function Harness({ initial = "", onChange }: { initial?: string; onChange?: (v: string) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <InstructionsEditor
      label="Instructions"
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
      variables={VARIABLES}
      mode="source"
    />
  );
}

function type(text: string) {
  const box = screen.getByRole("textbox", { name: "Instructions" }) as HTMLTextAreaElement;
  box.setSelectionRange(box.value.length, box.value.length);
  fireEvent.change(box, { target: { value: text, selectionStart: text.length } });
  return box;
}

describe("InstructionsEditor", () => {
  it("offers variables after {{ and inserts the chosen one with Enter", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    const box = type("Hi {{us");
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(screen.getAllByRole("option")).toHaveLength(1);
    fireEvent.keyDown(box, { key: "Enter" });

    expect(onChange).toHaveBeenLastCalledWith("Hi {{user_name}}");
  });

  it("moves through the list with the arrows and inserts with Tab or a click", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    const box = type("{{");
    fireEvent.keyDown(box, { key: "ArrowDown" });
    fireEvent.keyDown(box, { key: "ArrowDown" });
    fireEvent.keyDown(box, { key: "ArrowUp" });
    fireEvent.keyDown(box, { key: "Tab" });
    expect(onChange).toHaveBeenLastCalledWith("{{current_time}}");

    type("{{current_time}} {{");
    fireEvent.mouseDown(screen.getByText("{{user_name}}"));
    fireEvent.click(screen.getByText("{{user_name}}"));
    expect(onChange).toHaveBeenLastCalledWith("{{current_time}} {{user_name}}");
  });

  it("closes on Escape, and leaves other keys and closed braces alone", () => {
    render(<Harness />);

    const box = type("{{");
    fireEvent.keyDown(box, { key: "a" });
    fireEvent.keyDown(box, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

    type("{{user_name}} done");
    fireEvent.keyDown(box, { key: "Enter" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

it("keeps variable suggestions and caret integration in the expanded editor", async () => {
  const onChange = vi.fn();
  render(<Harness onChange={onChange} />);
  fireEvent.click(screen.getByRole("button", { name: "Expand Instructions" }));
  const dialog = screen.getByRole("dialog", { name: "Instructions" });
  const box = within(dialog).getByRole("textbox", { name: "Instructions" });
  fireEvent.change(box, { target: { value: "Hi {{", selectionStart: 5 } });
  expect(within(dialog).getByRole("listbox")).toBeInTheDocument();
  fireEvent.keyDown(box, { key: "ArrowDown" });
  fireEvent.keyDown(box, { key: "Tab" });
  expect(onChange).toHaveBeenLastCalledWith("Hi {{current_time}}");
  await waitFor(() => expect(box).toHaveFocus());
  expect(box).toHaveValue("Hi {{current_time}}");
  fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
  expect(screen.getByRole("textbox", { name: "Instructions" })).toHaveValue("Hi {{current_time}}");
});
