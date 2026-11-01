import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { MarkdownCellEditor } from "./markdown-cell-editor";
vi.mock("./document-templates", () => ({
  DocumentTemplates: ({ onApply }: { onApply: (body: string) => void }) => (
    <button onClick={() => onApply("# Library")}>Library template</button>
  ),
}));
const props = { id: "notes", label: "Notes", onCommit: vi.fn() };
it.each([
  ["Bold", "H**ell**o"],
  ["Italic", "H_ell_o"],
  ["Insert link", "H[ell](https://)o"],
  ["Insert image", "H![ell](https://)o"],
  ["Insert video", "H[ell](https://example.com/video.mp4)o"],
])("formats the selected text with %s", async (name, expected) => {
  const change = vi.fn();
  render(<MarkdownCellEditor {...props} value="Hello" onChange={change} />);
  const input = screen.getByRole("textbox", { name: "Notes" });
  if (!(input instanceof HTMLTextAreaElement)) throw new Error("Missing editor");
  input.setSelectionRange(1, 4);
  await userEvent.click(screen.getByRole("button", { name }));
  expect(change).toHaveBeenLastCalledWith(expected);
  await waitFor(() => expect(input).toHaveFocus());
});
it("refuses to format an editor removed from its document", async () => {
  const change = vi.fn();
  render(<MarkdownCellEditor {...props} value="Hello" onChange={change} />);
  screen.getByRole("textbox", { name: "Notes" }).remove();
  await userEvent.click(screen.getByRole("button", { name: "Bold" }));
  expect(change).not.toHaveBeenCalled();
});
it("applies a library body immediately to an empty document", async () => {
  const change = vi.fn();
  render(
    <MarkdownCellEditor {...props} tableId="table" columnId="column" value="" onChange={change} />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Library template" }));
  expect(change).toHaveBeenCalledWith("# Library");
});
it("allows cancelling or confirming a library replacement, preserving the header", async () => {
  const change = vi.fn();
  render(
    <MarkdownCellEditor
      {...props}
      tableId="table"
      columnId="column"
      value={"---\nowner: Ada\n---\n# Original"}
      onChange={change}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Library template" }));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
  expect(change).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Library template" }));
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Use template" }),
  );
  expect(change).toHaveBeenCalledWith("---\nowner: Ada\n---\n# Library");
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  expect(screen.getByRole("textbox", { name: "Notes" })).toHaveFocus();
});
it("starts an empty document from its configured column template", async () => {
  const change = vi.fn();
  render(<MarkdownCellEditor {...props} value="" template="# Default" onChange={change} />);
  await userEvent.click(screen.getByRole("button", { name: "Use column template" }));
  expect(change).toHaveBeenCalledWith("# Default");
});
