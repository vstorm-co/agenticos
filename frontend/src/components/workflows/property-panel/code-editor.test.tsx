import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { CodeLanguage } from "@/lib/workflows/code-editing";

import { CodeEditor } from "./code-editor";

function Harness({
  initial = "",
  language = "python",
  argKeys = [],
  onChange = vi.fn(),
}: {
  initial?: string;
  language?: CodeLanguage;
  argKeys?: string[];
  onChange?: (next: string) => void;
}) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <CodeEditor
        id="code"
        language={language}
        label="Code"
        value={value}
        argKeys={argKeys}
        onChange={(next) => {
          onChange(next);
          setValue(next);
        }}
      />
      <button type="button">after</button>
    </>
  );
}

const editor = () => screen.getByRole("textbox", { name: "Code" }) as HTMLTextAreaElement;

describe("CodeEditor", () => {
  it("indents with Tab, keeps indentation on Enter and closes brackets", async () => {
    render(<Harness />);
    await userEvent.click(editor());
    await userEvent.keyboard("if x:{Enter}f({Enter}");
    expect(editor().value).toBe("if x:\n    f(\n        \n    )");
    await userEvent.keyboard("{Backspace}{Backspace}{Backspace}{Backspace}{Backspace}");
    await userEvent.keyboard("{Tab}");
    expect(editor().value).toBe(`if x:\n    f(\n${" ".repeat(7)}\n    )`);
  });

  it("types a closer over the one already there, and erases an empty pair at once", async () => {
    render(<Harness initial="" language="javascript" />);
    await userEvent.click(editor());
    await userEvent.keyboard("g[[]");
    expect(editor().value).toBe("g[]");
    await userEvent.keyboard("{ArrowLeft}{Backspace}");
    expect(editor().value).toBe("g");
  });

  it("scrolls its highlighted copy with the text", () => {
    const { container } = render(<Harness initial={"x\n".repeat(60)} />);
    const underlay = container.querySelector("pre") as HTMLPreElement;
    editor().scrollTop = 120;
    editor().scrollLeft = 8;
    fireEvent.scroll(editor());
    expect([underlay.scrollTop, underlay.scrollLeft]).toEqual([120, 8]);
  });

  it("marks the bracket beside the caret and its match, scrolled with the text", async () => {
    render(<Harness initial={"f(a)\n".repeat(40)} />);
    editor().scrollTop = 60;
    await userEvent.click(editor());
    editor().setSelectionRange(2, 2);
    fireEvent.select(editor());

    const layer = screen.getByTestId("bracket-match");
    expect([...layer.querySelectorAll("mark")].map((mark) => mark.textContent)).toEqual(["(", ")"]);
    expect(layer.scrollTop).toBe(60);
    editor().scrollTop = 90;
    fireEvent.scroll(editor());
    expect(layer.scrollTop).toBe(90);

    editor().setSelectionRange(0, 0);
    fireEvent.select(editor());
    expect(screen.queryByTestId("bracket-match")).not.toBeInTheDocument();
  });

  it("lets Tab leave once Escape is pressed", async () => {
    render(<Harness />);
    await userEvent.click(editor());
    await userEvent.keyboard("{Escape}{Tab}");
    expect(screen.getByRole("button", { name: "after" })).toHaveFocus();
  });

  it("leaves shortcuts with a modifier to the browser", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.click(editor());
    await userEvent.keyboard("{Control>}({/Control}");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("offers the keys of args as one is typed, by keyboard and by pointer", async () => {
    render(<Harness argKeys={["name", "score"]} />);
    await userEvent.click(editor());
    await userEvent.keyboard("args[['");
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "name",
      "score",
    ]);
    await userEvent.keyboard("{ArrowDown}{ArrowUp}{ArrowUp}{Enter}");
    expect(editor().value).toBe("args['score']");

    await userEvent.keyboard(" + args[['n");
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual(["name"]);
    await userEvent.pointer({ keys: "[MouseLeft]", target: screen.getByRole("option") });
    expect(editor().value).toBe("args['score'] + args['name']");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("completes a dotted key in JavaScript with Tab, and hides the list on Escape", async () => {
    render(<Harness language="javascript" argKeys={["rows"]} />);
    await userEvent.click(editor());
    await userEvent.keyboard("args.r");
    expect(screen.getByRole("listbox")).toBeVisible();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    await userEvent.keyboard("o{Tab}");
    expect(editor().value).toBe("args.rows");
  });
});
