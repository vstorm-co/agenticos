import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FileEditor } from "./file-editor";

/**
 * A named draft, read or edited.
 *
 * The default matters, and it changed: this pane opens on the **source**.
 * Somebody who came to a file in a console is usually there to read what it
 * says - the markup, the front matter, the line that will not parse - and a
 * rendered view is exactly what hides that. The preview is one click away and
 * most of the tests below take it, because what they are about is what the
 * preview draws rather than which half opens first.
 *
 * The HTML preview is sandboxed with no allowances at all. It is somebody's
 * uploaded file rendered to be looked at; scripts, forms and same-origin access
 * are all things it has no reason to need.
 *
 * These moved here with the component. It was `FileViewer` in
 * `components/skills`, which is both a name `components/files` had already taken
 * and a reason `/context` shipped a bare textarea instead of reusing it.
 */

vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="rendered">{content}</div>
  ),
}));

function mount(props: Partial<Parameters<typeof FileEditor>[0]> = {}) {
  const onChange = vi.fn();
  render(
    <FileEditor name="checklist.md" content="# Heading" canEdit onChange={onChange} {...props} />,
  );
  return { onChange };
}

/** The same pane, opened on its rendered half - what most of these assert on. */
function mountPreview(props: Partial<Parameters<typeof FileEditor>[0]> = {}) {
  return mount({ initialMode: "preview", ...props });
}

describe("the file editor", () => {
  it("opens on the source, because that is what somebody came to read", () => {
    // It used to open on the preview. A console shows a file to answer a
    // question about its contents - which key is misspelt, why the front
    // matter is rejected - and a rendered view is what hides the answer.
    mount();

    expect(screen.getByRole("textbox")).toHaveValue("# Heading");
    expect(screen.queryByTestId("rendered")).not.toBeInTheDocument();
  });

  it("renders the markdown once the preview is asked for", () => {
    mountPreview();

    expect(screen.getByTestId("rendered")).toHaveTextContent("# Heading");
  });

  it("switches to the source when asked", async () => {
    mount();

    await userEvent.click(screen.getByRole("button", { name: "Source" }));

    expect(screen.getByLabelText("checklist.md source")).toHaveValue("# Heading");
  });

  it("reports edits from the source view", async () => {
    const { onChange } = mount({ content: "" });

    await userEvent.click(screen.getByRole("button", { name: "Source" }));
    await userEvent.type(screen.getByLabelText("checklist.md source"), "x");

    expect(onChange).toHaveBeenCalledWith("x");
  });

  it("makes the source read-only for somebody who may not edit", async () => {
    mount({ canEdit: false });

    await userEvent.click(screen.getByRole("button", { name: "Source" }));

    expect(screen.getByLabelText("checklist.md source")).toHaveAttribute("readonly");
  });

  it("says an empty file is empty rather than rendering nothing", () => {
    mountPreview({ content: "   " });

    expect(screen.getByText("This file is empty.")).toBeInTheDocument();
  });

  it("says it is loading rather than showing an empty file", () => {
    mount({ loading: true, content: "" });

    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("sandboxes an HTML file with no allowances", () => {
    // Somebody's uploaded file, rendered to be looked at. Scripts, forms and
    // same-origin access are all things it has no reason to need.
    mountPreview({ name: "page.html", content: "<p>hi</p>" });

    const frame = screen.getByTitle("page.html, rendered");
    expect(frame).toHaveAttribute("sandbox", "");
    expect(frame).toHaveAttribute("srcdoc", "<p>hi</p>");
  });

  it("fences a code file with its own extension so it is highlighted", () => {
    // Rather than growing a second highlighter for code.
    mountPreview({ name: "helper.py", content: "print(1)" });

    expect(screen.getByTestId("rendered")).toHaveTextContent("```py");
  });

  it("shows a file it has no renderer for as the text it is", () => {
    // A `.txt` or an extensionless file is still worth reading; fencing it as
    // code would invent a language for it, and an HTML frame would be worse.
    mountPreview({ name: "NOTES", content: "plain words" });

    expect(screen.getByText("plain words")).toBeInTheDocument();
  });

  it("goes back to the rendered view from the source", async () => {
    // Reading is the common case, so the way back has to be one click - and the
    // toggle is the only thing that says which view is current.
    mount({ name: "checklist.md", content: "# Checks" });

    await userEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.getByLabelText("checklist.md source")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(screen.queryByLabelText("checklist.md source")).toBeNull();
  });

  it("offers removal only where it is allowed and asked for", async () => {
    const onDelete = vi.fn();
    mount({ onDelete });

    await userEvent.click(screen.getByRole("button", { name: "Remove checklist.md" }));

    expect(onDelete).toHaveBeenCalled();
  });

  it("offers no removal to somebody who may not edit", () => {
    mount({ canEdit: false, onDelete: vi.fn() });

    expect(screen.queryByRole("button", { name: "Remove checklist.md" })).toBeNull();
  });

  it("renders whatever footer the owner supplies", () => {
    mount({ footer: <span>a footer</span> });

    expect(screen.getByText("a footer")).toBeInTheDocument();
  });

  it("renders the owner's own fields above the content", () => {
    mount({ header: <span>the header</span> });

    expect(screen.getByText("the header")).toBeInTheDocument();
  });
});
