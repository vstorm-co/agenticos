import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RecordCellEditor } from "./record-cell-editor";
import { uploadTableImage, discardTableImage } from "@/lib/tables-api";
import { markdownDocument } from "@/lib/markdown-document";
import type { ColumnDef } from "@/types/tables";

vi.mock("@/lib/tables-api", () => ({
  uploadTableImage: vi.fn(),
  discardTableImage: vi.fn().mockResolvedValue(undefined),
}));

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
  it("keeps automatic record metadata without a separate property editor", async () => {
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
    expect(screen.getAllByText("member-1")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Write" }));
    expect(screen.getByRole("textbox", { name: "Notes" })).toHaveValue(
      markdownDocument(source).body,
    );
    expect(screen.queryByText("Custom properties")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add property" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Notes" }), {
      target: { value: "# Revised body" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Outside" }));
    expect(change).toHaveBeenLastCalledWith(expect.stringContaining("# Revised body"));
    expect(change).toHaveBeenLastCalledWith(expect.stringContaining("title: Example"));
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
    await userEvent.click(confirm.getByRole("button", { name: "Use template" }));
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
    expect(screen.queryByText("Custom properties")).not.toBeInTheDocument();
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

it("inserts a todo from the searchable slash menu using the keyboard", async () => {
  const change = vi.fn();
  render(
    <>
      <RecordCellEditor column={column} value={"Before\n"} onChange={change} />
      <button>Outside</button>
    </>,
  );
  const input = screen.getByRole("textbox", { name: "Notes" });
  await userEvent.click(input);
  if (!(input instanceof HTMLTextAreaElement)) throw new Error("Expected textarea");
  input.setSelectionRange(input.value.length, input.value.length);
  await userEvent.keyboard("/todo");
  expect(input).toHaveValue("Before\n/todo");
  expect(screen.getByRole("listbox", { name: "Insert a block" })).toBeVisible();
  await userEvent.keyboard("{Enter}");
  expect(input).toHaveValue("Before\n- [ ] ");
  await userEvent.click(screen.getByRole("button", { name: "Outside" }));
  expect(change).toHaveBeenCalledWith("Before\n- [ ] ");
});

it("does not treat a slash inside a URL as a block command", async () => {
  render(<RecordCellEditor column={column} value="" onChange={vi.fn()} />);
  await userEvent.type(screen.getByRole("textbox", { name: "Notes" }), "https://example.test/");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});

it("pastes an image at the cursor, saves its scoped address and preserves surrounding text", async () => {
  vi.mocked(uploadTableImage).mockResolvedValueOnce({
    id: "image",
    url: "/api/tables/table/media/image",
  });
  const change = vi.fn();
  render(
    <RecordCellEditor tableId="table" column={column} value="Before after" onChange={change} />,
  );
  const input = screen.getByRole("textbox", { name: "Notes" });
  await userEvent.click(input);
  if (!(input instanceof HTMLTextAreaElement)) throw new Error("Expected a textarea");
  input.setSelectionRange(7, 7);
  const file = new File(["PNG"], "clipboard.png", { type: "image/png" });
  fireEvent.paste(input, { clipboardData: { files: [file] } });
  await waitFor(() =>
    expect(change).toHaveBeenCalledWith("Before ![](/api/tables/table/media/image)after"),
  );
  expect(uploadTableImage).toHaveBeenCalledWith("table", file);
});

it("keeps the document unchanged and explains a failed image upload", async () => {
  vi.mocked(uploadTableImage).mockRejectedValueOnce(new Error("Denied"));
  const change = vi.fn();
  render(<RecordCellEditor tableId="table" column={column} value="Keep me" onChange={change} />);
  const input = screen.getByRole("textbox", { name: "Notes" });
  fireEvent.paste(input, {
    clipboardData: { files: [new File(["PNG"], "clipboard.png", { type: "image/png" })] },
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not paste the image");
  expect(input).toHaveValue("Keep me");
  expect(change).not.toHaveBeenCalled();
});

it("navigates block choices and lets Escape close the menu without replacing text", async () => {
  render(<RecordCellEditor column={column} value="" onChange={vi.fn()} />);
  const input = screen.getByRole("textbox", { name: "Notes" });
  await userEvent.type(input, "/");
  await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowUp}{Enter}");
  expect(input).toHaveValue("## ");
  await userEvent.clear(input);
  await userEvent.type(input, "/missing-block");
  expect(screen.getByText("No matching blocks")).toBeVisible();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(input).toHaveValue("/missing-block");
});

it("ignores a completed image upload after the record editor unmounts", async () => {
  let finish: ((image: { id: string; url: string }) => void) | undefined;
  vi.mocked(uploadTableImage).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const change = vi.fn();
  const mounted = render(
    <RecordCellEditor tableId="table" column={column} value="Keep" onChange={change} />,
  );
  fireEvent.paste(screen.getByRole("textbox", { name: "Notes" }), {
    clipboardData: { files: [new File(["PNG"], "image.png", { type: "image/png" })] },
  });
  expect(screen.getByRole("status")).toHaveTextContent("Uploading image");
  mounted.unmount();
  finish?.({ id: "late", url: "/api/tables/table/media/late" });
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(change).not.toHaveBeenCalled();
  expect(discardTableImage).toHaveBeenCalledWith("table", "late");
});

it("opens a full-page document in Write and returns to Preview in its side panel", () => {
  const metadata = { created_at: "2026-10-31T00:00:00Z", updated_at: null };
  const { rerender } = render(
    <RecordCellEditor
      column={column}
      value="# A document"
      metadata={metadata}
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: "Preview" })).toHaveAttribute("aria-pressed", "true");
  rerender(
    <RecordCellEditor
      column={column}
      value="# A document"
      metadata={metadata}
      fillEditor
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByRole("textbox", { name: "Notes" })).toHaveValue("# A document");
  expect(screen.getByRole("button", { name: "Write" })).toHaveAttribute("aria-pressed", "true");
});

it("releases earlier pasted images when a later upload fails", async () => {
  vi.mocked(uploadTableImage)
    .mockResolvedValueOnce({ id: "first", url: "/first" })
    .mockRejectedValueOnce(new Error("Quota"));
  const change = vi.fn();
  render(<RecordCellEditor tableId="table" column={column} value="Keep" onChange={change} />);
  fireEvent.paste(screen.getByRole("textbox", { name: "Notes" }), {
    clipboardData: {
      files: [
        new File(["png"], "one.png", { type: "image/png" }),
        new File(["png"], "two.png", { type: "image/png" }),
      ],
    },
  });
  await waitFor(() => expect(discardTableImage).toHaveBeenCalledWith("table", "first"));
  expect(change).not.toHaveBeenCalled();
  expect(screen.getByRole("textbox", { name: "Notes" })).toHaveValue("Keep");
});
