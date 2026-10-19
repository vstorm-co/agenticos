import { fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { CodeArea } from "./code-area";

/** The drawn copy under the textarea. */
const underlay = (container: HTMLElement) => container.querySelector("pre")!;

describe("CodeArea - a textarea that shows its own structure", () => {
  it("draws Markdown with its markers kept, and every character in place", () => {
    const text = "# Title\nUse **bold**, `code` and {{user_name}}.";
    const { container } = render(<CodeArea name="SKILL.md" aria-label="Body" value={text} />);

    expect(underlay(container).textContent).toBe(`${text}\n`);
    expect(screen.getByText("bold")).toHaveClass("text-foreground");
    expect(screen.getAllByText("**")[0]).toHaveClass("text-muted-foreground/70");
    expect(screen.getByText("{{user_name}}")).toHaveClass("text-violet-700");
  });

  it("draws a file with no syntax as it is", () => {
    const { container } = render(<CodeArea name="notes.txt" aria-label="Body" value="**x**" />);
    expect(underlay(container).textContent).toBe("**x**\n");
    expect(underlay(container).querySelector("span")).toBeNull();
  });

  it("reports the text and the caret, and keeps the drawing scrolled with it", () => {
    const onChange = vi.fn();
    const ref = createRef<HTMLTextAreaElement>();
    const { container } = render(
      <CodeArea
        name="a.md"
        aria-label="Body"
        value=""
        onChange={onChange}
        textareaRef={ref}
        id="body"
        invalid
        describedBy="body-error"
        maxLength={10}
      />,
    );
    const box = screen.getByRole("textbox", { name: "Body" });
    expect(ref.current).toBe(box);
    expect(box).toHaveAttribute("aria-invalid", "true");
    expect(box).toHaveAttribute("aria-describedby", "body-error");
    expect(box).toHaveAttribute("maxlength", "10");

    fireEvent.change(box, { target: { value: "hi", selectionStart: 2 } });
    expect(onChange).toHaveBeenCalledWith("hi", 2);

    box.scrollTop = 40;
    fireEvent.scroll(box);
    expect(underlay(container).scrollTop).toBe(40);
  });

  it("is read-only without a change handler", () => {
    render(<CodeArea name="a.md" aria-label="Body" value="x" readOnly />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "y" } });
    expect(screen.getByRole("textbox")).toHaveAttribute("readonly");
  });
});
