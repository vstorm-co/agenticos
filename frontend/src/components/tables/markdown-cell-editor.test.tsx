import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RecordCellEditor } from "./record-cell-editor";
import { markdownDocument } from "@/lib/markdown-document";
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
  it("edits properties above Markdown and protects automatic metadata", async () => {
    const change = vi.fn();
    render(
      <>
        <RecordCellEditor
          column={column}
          value={source}
          metadata={{
            created_at: "2026-10-01T10:00:00Z",
            updated_at: "2026-10-02T10:00:00Z",
            created_by: "member-1",
          }}
          onChange={change}
        />
        <button>Outside</button>
      </>,
    );
    expect(screen.getByText("Created")).toBeVisible();
    expect(screen.getByText("Last updated")).toBeVisible();
    expect(screen.getByText("member-1")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Notes" })).toHaveValue(
      markdownDocument(source).body,
    );
    await userEvent.click(screen.getByText("Custom properties"));
    fireEvent.change(screen.getByRole("textbox", { name: "title" }), {
      target: { value: "Revised" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Property name" }), {
      target: { value: "created_at" },
    });
    expect(screen.getByRole("button", { name: "Add property" })).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: "Property name" }), {
      target: { value: "owner" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Property value" }), {
      target: { value: "Sam" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Add property" }));
    await userEvent.click(screen.getByRole("button", { name: "Outside" }));
    expect(change).toHaveBeenLastCalledWith(expect.stringContaining("owner: Sam"));
    expect(change).toHaveBeenLastCalledWith(expect.stringContaining("title: Revised"));
  });

  it("confirms applying a new template without replacing document properties", async () => {
    const change = vi.fn();
    render(
      <>
        <RecordCellEditor
          column={{ ...column, default: "# New note" }}
          value={source}
          onChange={change}
        />
        <button>Outside</button>
      </>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Use column template" }));
    const confirm = within(screen.getByRole("dialog", { name: "Replace document content?" }));
    await userEvent.click(confirm.getByRole("button", { name: "Use column template" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Notes" })).toHaveFocus());
    expect(screen.getByRole("textbox", { name: "Notes" })).toHaveValue("# New note");
    await userEvent.click(screen.getByRole("button", { name: "Outside" }));
    expect(change).toHaveBeenLastCalledWith(expect.stringContaining("title: Example"));
    expect(change).toHaveBeenLastCalledWith(expect.stringContaining("# New note"));
  });

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
    await userEvent.click(screen.getByText("Custom properties"));
    expect(screen.getByRole("textbox", { name: "title", hidden: true })).toHaveValue("Example");
    await userEvent.click(screen.getByRole("button", { name: "Write" }));
    expect(screen.getByRole("textbox", { name: "Notes" })).toHaveValue(
      markdownDocument(source).body,
    );
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
      target: { value: markdownDocument(source).body + "More\n" },
    });
    await userEvent.click(dialog.getByRole("button", { name: "Done" }));
    expect(change).toHaveBeenCalledTimes(1);
    expect(change).toHaveBeenCalledWith(source + "More\n");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Notes" })).toHaveValue(
      markdownDocument(source).body + "More\n",
    );
  });

  it("commits once on Escape and returns focus from the expanded dialog", async () => {
    const change = vi.fn();
    render(<RecordCellEditor column={column} value={source} onChange={change} />);
    await userEvent.click(screen.getByRole("button", { name: "Expand editor" }));
    const editor = within(screen.getByRole("dialog")).getByRole("textbox", { name: "Notes" });
    await userEvent.click(editor);
    fireEvent.change(editor, { target: { value: markdownDocument(source).body + "Updated" } });
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(change).toHaveBeenCalledTimes(1);
    expect(change).toHaveBeenCalledWith(source + "Updated");
    expect(screen.getByRole("button", { name: "Expand editor" })).toHaveFocus();
  });

  it("starts read-only cells in preview and renders images while refusing executable HTML", async () => {
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
    expect(screen.getByRole("img", { name: "Remote" })).toHaveAttribute(
      "src",
      "https://example.test/pixel.png",
    );
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
