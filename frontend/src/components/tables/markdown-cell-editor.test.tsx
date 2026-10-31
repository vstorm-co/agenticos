import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RecordCellEditor } from "./record-cell-editor";
import type { ColumnDef } from "@/types/tables";

const column: ColumnDef = {
  id: "notes",
  label: "Notes",
  type: "rich_text",
  nullable: true,
  default: null,
  options: [],
  archived: false,
};
const source =
  "---\ntitle: Example\ntags: [team, notes]\n---\n# Meeting\n\n**Important**\n\n- [x] Done\n";

describe("Markdown table cells", () => {
  it("buffers Markdown and frontmatter, switches views without saving and commits on leaving", async () => {
    const change = vi.fn();
    render(
      <>
        <RecordCellEditor column={column} value="" onChange={change} />
        <button>Outside</button>
      </>,
    );
    const input = screen.getByRole("textbox", { name: "Notes" });
    fireEvent.change(input, { target: { value: source } });
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(change).not.toHaveBeenCalled();
    expect(await screen.findByRole("heading", { name: "Meeting" })).toBeVisible();
    expect(screen.getByText("Important").tagName).toBe("STRONG");
    await userEvent.click(screen.getByText("Frontmatter"));
    expect(screen.getByText(/title: Example/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Write" }));
    expect(screen.getByRole("textbox", { name: "Notes" })).toHaveValue(source);
    await userEvent.click(screen.getByRole("button", { name: "Outside" }));
    expect(change).toHaveBeenCalledTimes(1);
    expect(change).toHaveBeenCalledWith(source);
  });

  it("edits in an expanded dialog, commits once on Done and keeps the draft after closing", async () => {
    const change = vi.fn();
    render(<RecordCellEditor column={column} value={source} onChange={change} />);
    await userEvent.click(screen.getByRole("button", { name: "Expand editor" }));
    const dialog = within(screen.getByRole("dialog", { name: "Notes" }));
    fireEvent.change(dialog.getByRole("textbox", { name: "Notes" }), {
      target: { value: source + "More\n" },
    });
    await userEvent.click(dialog.getByRole("button", { name: "Done" }));
    expect(change).toHaveBeenCalledTimes(1);
    expect(change).toHaveBeenCalledWith(source + "More\n");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Notes" })).toHaveValue(source + "More\n");
  });

  it("commits once on Escape and returns focus from the expanded dialog", async () => {
    const change = vi.fn();
    render(<RecordCellEditor column={column} value={source} onChange={change} />);
    await userEvent.click(screen.getByRole("button", { name: "Expand editor" }));
    const editor = within(screen.getByRole("dialog")).getByRole("textbox", { name: "Notes" });
    await userEvent.click(editor);
    fireEvent.change(editor, { target: { value: source + "Updated" } });
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(change).toHaveBeenCalledTimes(1);
    expect(change).toHaveBeenCalledWith(source + "Updated");
    expect(screen.getByRole("button", { name: "Expand editor" })).toHaveFocus();
  });

  it("starts read-only cells in preview and never renders executable HTML or remote images", async () => {
    render(
      <RecordCellEditor
        column={column}
        value={
          "# Read only\n\n<script>alert(1)</script>\n\n![Remote](https://example.test/pixel.png)"
        }
        onChange={vi.fn()}
        disabled
      />,
    );
    expect(await screen.findByRole("heading", { name: "Read only" })).toBeVisible();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Write" }));
    expect(screen.getByRole("textbox", { name: "Notes" })).toBeDisabled();
  });

  it("shows an empty preview, associates validation with the editor and follows a new server value", async () => {
    const { rerender } = render(
      <RecordCellEditor column={column} value="" onChange={vi.fn()} error="Required" />,
    );
    expect(screen.getByRole("textbox", { name: "Notes" })).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("textbox", { name: "Notes" })).toHaveAccessibleDescription("Required");
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(screen.getByText("Nothing to preview yet.")).toBeVisible();
    rerender(<RecordCellEditor column={column} value="# Updated" onChange={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "Updated" })).toBeVisible();
  });
});
