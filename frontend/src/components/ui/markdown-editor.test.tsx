import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MarkdownEditor, MarkdownModeToggle } from "./markdown-editor";

// The real renderer is a `next/dynamic` import of react-markdown. What matters
// here is that the preview pane shows the value rather than the textarea, so the
// renderer is stood in for by something that simply prints what it was given.
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content, inertImages }: { content: string; inertImages?: boolean }) => (
    <div data-testid="rendered" data-inert-images={String(Boolean(inertImages))}>
      {content}
    </div>
  ),
}));

function mount(props: Partial<Parameters<typeof MarkdownEditor>[0]> = {}) {
  const onChange = vi.fn();
  render(<MarkdownEditor value="# Heading" onChange={onChange} label="Instructions" {...props} />);
  return { onChange };
}

describe("the markdown editor", () => {
  it("opens on the source, because a form field should be editable when you reach it", () => {
    // The skill editor's file viewer opens on the preview - somebody clicked a
    // file in a tree to read it. A field on a form is the opposite: the reason
    // it is on screen is that somebody came to change it.
    mount();

    expect(screen.getByLabelText("Instructions")).toHaveValue("# Heading");
    expect(screen.queryByTestId("rendered")).toBeNull();
  });

  it("renders the markdown once the preview is asked for", async () => {
    mount();

    await userEvent.click(screen.getByRole("button", { name: "Preview" }));

    expect(screen.getByTestId("rendered")).toHaveTextContent("# Heading");
    expect(screen.queryByLabelText("Instructions")).toBeNull();
  });

  it("previews text somebody else wrote without fetching its images, when asked to", async () => {
    mount({ inertImages: true });

    await userEvent.click(screen.getByRole("button", { name: "Preview" }));

    expect(screen.getByTestId("rendered")).toHaveAttribute("data-inert-images", "true");
  });

  it("comes back to the source with the value intact", async () => {
    mount();

    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    await userEvent.click(screen.getByRole("button", { name: "Source" }));

    expect(screen.getByLabelText("Instructions")).toHaveValue("# Heading");
  });

  it("reports every keystroke to the caller", async () => {
    // The Builder autosaves off this callback; a control that batched or
    // swallowed changes would lose work with no error anywhere.
    const { onChange } = mount({ value: "" });

    await userEvent.type(screen.getByLabelText("Instructions"), "ab");

    expect(onChange).toHaveBeenCalledTimes(2);
    // With where the caret ended up, for a caller completing what is typed.
    expect(onChange).toHaveBeenLastCalledWith("b", 1);
  });

  it("says the preview is empty rather than rendering nothing", async () => {
    // An empty pane and a broken renderer look identical.
    mount({ value: "   " });

    await userEvent.click(screen.getByRole("button", { name: "Preview" }));

    expect(screen.getByText("Nothing written yet.")).toBeInTheDocument();
  });

  it("uses the label as the accessible name, not the placeholder", () => {
    // A placeholder is the one label that disappears the moment somebody types.
    mount({ label: "Skill body", placeholder: "You are..." });

    expect(screen.getByLabelText("Skill body")).toBeInTheDocument();
  });

  it("names the preview region after the field it previews", async () => {
    // Otherwise the two halves of one control are two unrelated regions to a
    // screen reader.
    mount();

    await userEvent.click(screen.getByRole("button", { name: "Preview" }));

    expect(screen.getByRole("region", { name: "Instructions preview" })).toBeInTheDocument();
  });

  it("stops the field being edited when the caller says so", () => {
    // A Viewer opening the Builder must not be able to type into the agent's
    // instructions, whatever the save endpoint would then refuse.
    mount({ disabled: true });

    expect(screen.getByLabelText("Instructions")).toBeDisabled();
  });

  it("still lets a read-only caller read the preview", async () => {
    // `disabled` is about writing. Someone who may view an agent may read what
    // its instructions say.
    mount({ disabled: true });

    await userEvent.click(screen.getByRole("button", { name: "Preview" }));

    expect(screen.getByTestId("rendered")).toHaveTextContent("# Heading");
  });

  it("leaves the toggle to a caller that holds the mode, and draws what it is told", () => {
    mount({ mode: "preview" });

    expect(screen.queryByRole("button", { name: "Source" })).toBeNull();
    expect(screen.getByRole("region", { name: "Instructions preview" })).toBeInTheDocument();
  });
});

describe("MarkdownModeToggle", () => {
  it("marks the open mode and answers a click", async () => {
    const onChange = vi.fn();
    render(<MarkdownModeToggle mode="source" onChange={onChange} />);

    expect(screen.getByRole("button", { name: "Source" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));

    expect(onChange).toHaveBeenCalledWith("preview");
  });
});
