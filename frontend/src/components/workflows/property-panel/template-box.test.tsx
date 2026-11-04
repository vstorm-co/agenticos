import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui";

import { TemplateBox } from "./template-box";
import type { Suggestion } from "./template-suggest";

const STEPS = ["Triage the ticket", "Triage", "Form"];

function mount(
  value: string,
  { multiline = true, unknown = null as string | null, disabled = false } = {},
) {
  const onChange = vi.fn();
  const { container } = render(
    <TemplateBox
      id="prompt"
      value={value}
      multiline={multiline}
      unknown={unknown}
      stepNames={STEPS}
      suggestions={[]}
      disabled={disabled}
      invalid={false}
      onChange={onChange}
      onBlur={vi.fn()}
    />,
  );
  const backdrop = container.querySelector("[data-template-backdrop]") as HTMLElement;
  const placeholders = () => Array.from(backdrop.querySelectorAll("[data-placeholder]"));
  const part = (element: Element, name: string) =>
    element.querySelector(`[data-part="${name}"]`) as HTMLElement;
  return { onChange, backdrop, placeholders, part };
}

describe("TemplateBox", () => {
  it("keeps the syntax backdrop visible through the editable control", () => {
    const { backdrop } = mount("A visible prompt");
    expect(screen.getByRole("textbox")).toHaveClass("bg-transparent");
    expect(backdrop).toHaveClass("bg-card", "text-foreground");
  });

  it("draws each placeholder as code: its step and its path coloured apart", () => {
    const { backdrop, placeholders, part } = mount(
      "Ticket {{Triage the ticket.category}} from {{ Form.payload.name }}",
    );
    const [category, name] = placeholders();
    // The longest step name wins, so "Triage" does not take the name's first word.
    expect(part(category!, "step")).toHaveTextContent("Triage the ticket");
    expect(part(category!, "path")).toHaveTextContent(".category");
    expect(part(category!, "step").className).toContain("text-[var(--domain-build)]");
    expect(part(category!, "path").className).toContain("text-[var(--domain-workspace)]");
    // Spaces inside the braces are kept, so the copy lines up with what was typed.
    expect(name).toHaveTextContent("{{ Form.payload.name }}");
    expect(part(name!, "path")).toHaveTextContent(".payload.name");
    // The copy is for the eye only, and every letter of it is there.
    expect(backdrop).toHaveAttribute("aria-hidden", "true");
    expect(backdrop).toHaveTextContent(
      "Ticket {{Triage the ticket.category}} from {{ Form.payload.name }}",
    );
  });

  it("colours a placeholder naming no step by its first name, and a whole step with no path", () => {
    const { placeholders, part } = mount("{{Other.x}} {{Form}}");
    const [other, form] = placeholders();
    expect(part(other!, "step")).toHaveTextContent("Other");
    expect(part(form!, "step")).toHaveTextContent("Form");
    expect(part(form!, "path")).toHaveTextContent("");
  });

  it("marks a placeholder naming nothing in reach in red", () => {
    const { placeholders } = mount("{{Gone.x}} and {{Form.name}}", { unknown: "{{Gone.x}}" });
    const [gone, known] = placeholders();
    expect(gone!.className).toContain("text-destructive");
    expect(gone!.className).toContain("decoration-wavy");
    expect(known!.className).not.toContain("text-destructive");
  });

  it("types in the box, which shows its caret over the coloured copy", () => {
    const { onChange } = mount("{{Form.name}}\n");
    const box = screen.getByRole("textbox");
    expect(box.className).toContain("text-transparent");
    expect(box.className).toContain("caret-foreground");
    fireEvent.change(box, { target: { value: "edited" } });
    expect(onChange).toHaveBeenCalledWith("edited");
  });

  it("keeps the copy scrolled with the box, and dimmed with it when read-only", () => {
    const { backdrop } = mount("{{Form.name}}", { disabled: true });
    const box = screen.getByRole("textbox");
    box.scrollTop = 40;
    box.scrollLeft = 7;
    fireEvent.scroll(box);
    expect(backdrop.scrollTop).toBe(40);
    expect(backdrop.scrollLeft).toBe(7);
    expect(backdrop.className).toContain("opacity-50");
  });

  it("lays a one-line box out on one line", () => {
    const { backdrop } = mount("{{Form.name}}", { multiline: false });
    expect(screen.getByRole("textbox").tagName).toBe("INPUT");
    expect(backdrop.className).toContain("whitespace-pre");
    expect(backdrop.className).not.toContain("whitespace-pre-wrap");
    // One line has no scrollbar to make room for: the copy is as wide as the box.
    expect(backdrop.className).not.toContain("scrollbar-gutter");
    expect(screen.getByRole("textbox").className).not.toContain("scrollbar-gutter");
  });
});

const OFFERED: Suggestion[] = [
  {
    text: "{{Triage the ticket.reason}}",
    step: "Triage the ticket",
    path: ".reason",
    type: "string",
  },
  { text: "{{Triage the ticket.text}}", step: "Triage the ticket", path: ".text", type: "string" },
  {
    text: "{{Manual.payload.customer}}",
    step: "Manual",
    path: ".payload.customer",
    type: "string",
  },
];

/** A box its owner keeps the text of, as a field does. */
function Owned({
  start = "",
  multiline = true,
  disabled = false,
}: {
  start?: string;
  multiline?: boolean;
  disabled?: boolean;
}) {
  const [text, setText] = useState(start);
  return (
    <TemplateBox
      id="prompt"
      value={text}
      multiline={multiline}
      unknown={null}
      stepNames={["Triage the ticket", "Manual"]}
      suggestions={OFFERED}
      disabled={disabled}
      invalid={false}
      onChange={setText}
      onBlur={vi.fn()}
    />
  );
}

describe("TemplateBox suggestions", () => {
  it("offers the values a placeholder can name once {{ is typed, narrowed by what follows", async () => {
    render(<Owned />);
    const box = screen.getByRole("textbox");
    await userEvent.type(box, "Hi ");
    expect(screen.queryByRole("listbox")).toBeNull();

    await userEvent.type(box, "{{{{");
    expect(screen.getAllByRole("option")).toHaveLength(3);
    await userEvent.type(box, "cust");
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Manual.payload.customerstring",
    ]);
    expect(box).toHaveAttribute("aria-controls", "prompt-suggestions");
    expect(box).toHaveAttribute("aria-activedescendant", "prompt-suggestions-0");
  });

  it("writes the picked one out with Enter, closing braces and all, caret after it", async () => {
    render(<Owned />);
    const box = screen.getByRole("textbox") as HTMLTextAreaElement;
    await userEvent.type(box, "Why: {{{{tri");
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Enter}");

    expect(box).toHaveValue("Why: {{Triage the ticket.text}}");
    expect(box.selectionStart).toBe(box.value.length);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("takes Tab and a click as well, and wraps the arrows round the list", async () => {
    render(<Owned />);
    const box = screen.getByRole("textbox");
    await userEvent.type(box, "{{{{");
    await userEvent.keyboard("{ArrowUp}");
    expect(screen.getAllByRole("option")[2]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Tab}");
    expect(box).toHaveValue("{{Manual.payload.customer}}");

    await userEvent.type(box, " {{{{");
    fireEvent.mouseDown(screen.getAllByRole("option")[0] as HTMLElement);
    expect(box).toHaveValue("{{Manual.payload.customer}} {{Triage the ticket.reason}}");
  });

  it("moves past the closing braces it was already inside when nothing changes", async () => {
    render(<Owned start="{{Triage the ticket.text}}" />);
    const box = screen.getByRole("textbox") as HTMLTextAreaElement;
    await userEvent.click(box);
    // Just before the `}}`: the list offers what is already written there.
    box.setSelectionRange(24, 24);
    fireEvent.select(box);
    await userEvent.keyboard("{Enter}");
    expect(box).toHaveValue("{{Triage the ticket.text}}");
    expect(box.selectionStart).toBe(26);
    // What is typed next lands after the placeholder, not inside its braces.
    await userEvent.keyboard("!");
    expect(box).toHaveValue("{{Triage the ticket.text}}!");
  });

  it("puts the list away on Escape without closing the dialog around the box", async () => {
    const onOpenChange = vi.fn();
    render(
      <Dialog open onOpenChange={onOpenChange}>
        <DialogContent aria-describedby={undefined}>
          <DialogTitle>Step</DialogTitle>
          <Owned />
        </DialogContent>
      </Dialog>,
    );
    const box = screen.getByRole("textbox");
    await userEvent.type(box, "{{{{");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(onOpenChange).not.toHaveBeenCalled();
    // The next keystroke brings it back.
    await userEvent.type(box, "t");
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    // Escape with no list open is the dialog's again.
    await userEvent.type(box, "zzz");
    await userEvent.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("offers nothing on a box turned read-only while a placeholder is being written", async () => {
    const { rerender } = render(<Owned start="{{" />);
    await userEvent.click(screen.getByRole("textbox"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    // The same box, its caret still inside the braces: the editor went View only.
    rerender(<Owned start="{{" disabled />);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("offers nothing once the caret leaves the box", async () => {
    render(<Owned start="{{" />);
    const box = screen.getByRole("textbox");
    await userEvent.click(box);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.blur(box);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("stays a text box while the list comes and goes, input and textarea alike", async () => {
    for (const multiline of [true, false]) {
      const { unmount } = render(<Owned multiline={multiline} />);
      const box = screen.getByRole("textbox");
      // A textbox takes no aria-expanded, and a textarea no combobox role.
      expect(box).toHaveAttribute("aria-autocomplete", "list");
      expect(box).not.toHaveAttribute("aria-expanded");
      expect(box).not.toHaveAttribute("aria-controls");
      await userEvent.type(box, "{{{{");
      expect(screen.getByRole("textbox")).toBe(box);
      expect(box).not.toHaveAttribute("role");
      expect(box).not.toHaveAttribute("aria-expanded");
      expect(box).toHaveAttribute("aria-controls", "prompt-suggestions");
      expect(box).toHaveAttribute("aria-activedescendant", "prompt-suggestions-0");
      await userEvent.keyboard("{Escape}");
      expect(box).not.toHaveAttribute("aria-controls");
      expect(box).not.toHaveAttribute("aria-activedescendant");
      unmount();
    }
  });
});

describe("TemplateBox's ref", () => {
  it("hands its box to a ref given as a function too", () => {
    const ref = vi.fn();
    render(
      <TemplateBox
        ref={ref}
        id="r"
        value=""
        multiline
        unknown={null}
        stepNames={[]}
        suggestions={[]}
        invalid={false}
        onChange={vi.fn()}
        onBlur={vi.fn()}
      />,
    );
    expect(ref).toHaveBeenCalledWith(screen.getByRole("textbox"));
  });
});
