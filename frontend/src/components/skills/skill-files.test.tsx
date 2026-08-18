import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FilePane, FileTree, NewFileForm, UploadButton, formatSize } from "./skill-files";
import { buildTree } from "@/lib/file-tree";
import type { SkillResourceSummary } from "@/types/providers";

/**
 * A skill's files - the tree, what fetches one, and the form that adds one.
 *
 * What the pane itself does is in `components/files/file-editor.test.tsx`, with
 * the component: it is not a skills idea, and `/context` needed the same one.
 * The draft is this file's business, because the content of a resource is not in
 * the listing - so Save and Discard have something to be about.
 */

const loaded = { content: undefined as string | undefined, isLoading: false };

vi.mock("@/hooks", () => ({
  useSkillResource: () => ({
    resource: loaded.content === undefined ? undefined : { content: loaded.content },
    isLoading: loaded.isLoading,
  }),
}));

vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="rendered">{content}</div>
  ),
}));

function resource(name: string, id = name): SkillResourceSummary {
  return { id, name, description: null, size_bytes: 100 } as SkillResourceSummary;
}

beforeEach(() => {
  loaded.content = "# Body";
  loaded.isLoading = false;
});

describe("formatSize", () => {
  it("keeps small files in bytes, where kilobytes would read as zero", () => {
    expect(formatSize(0)).toBe("0 B");
    expect(formatSize(1023)).toBe("1023 B");
  });

  it("switches to kilobytes with a decimal while that is informative", () => {
    expect(formatSize(1024)).toBe("1.0 KB");
    expect(formatSize(5120)).toBe("5.0 KB");
  });

  it("drops the decimal once the number is large enough not to need it", () => {
    expect(formatSize(10240)).toBe("10 KB");
    expect(formatSize(1048576)).toBe("1024 KB");
  });
});

describe("the file tree", () => {
  it("renders nothing at all for a skill with no files", () => {
    const { container } = render(<FileTree nodes={[]} openId={null} onOpen={vi.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("lists files at the top level", () => {
    const nodes = buildTree([resource("checklist.md")]);
    render(<FileTree nodes={nodes} openId={null} onOpen={vi.fn()} />);

    expect(screen.getByRole("tree")).toBeInTheDocument();
    expect(screen.getByText("checklist.md")).toBeInTheDocument();
  });

  it("opens the file that was clicked, by id rather than by name", async () => {
    // Two files can share a name in different folders; the id is what the pane
    // fetches by.
    const onOpen = vi.fn();
    const nodes = buildTree([resource("references/a.md", "id-a")]);
    render(<FileTree nodes={nodes} openId={null} onOpen={onOpen} />);

    await userEvent.click(screen.getByText("a.md"));

    expect(onOpen).toHaveBeenCalledWith("id-a");
  });

  it("marks the open file as the selection", () => {
    const nodes = buildTree([resource("a.md", "id-a"), resource("b.md", "id-b")]);
    render(<FileTree nodes={nodes} openId={"id-b"} onOpen={vi.fn()} />);

    const items = screen.getAllByRole("treeitem");
    expect(items.find((item) => item.textContent === "b.md")).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("never marks a folder as the selection, because a folder does not open", () => {
    const nodes = buildTree([resource("references/a.md", "id-a")]);
    render(<FileTree nodes={nodes} openId={"id-a"} onOpen={vi.fn()} />);

    const folder = screen
      .getAllByRole("treeitem")
      .find((item) => item.textContent?.startsWith("references"));
    expect(folder).toHaveAttribute("aria-selected", "false");
  });

  it("starts with folders expanded, so the files are visible", () => {
    const nodes = buildTree([resource("references/a.md", "id-a")]);
    render(<FileTree nodes={nodes} openId={null} onOpen={vi.fn()} />);

    expect(screen.getByText("a.md")).toBeInTheDocument();
    expect(screen.getByRole("treeitem", { expanded: true })).toBeInTheDocument();
  });

  it("collapses a folder and hides what is inside it", async () => {
    const nodes = buildTree([resource("references/a.md", "id-a")]);
    render(<FileTree nodes={nodes} openId={null} onOpen={vi.fn()} />);

    await userEvent.click(screen.getByText("references"));

    expect(screen.queryByText("a.md")).toBeNull();
    expect(screen.getByRole("treeitem", { expanded: false })).toBeInTheDocument();
  });

  it("expands it again", async () => {
    const nodes = buildTree([resource("references/a.md", "id-a")]);
    render(<FileTree nodes={nodes} openId={null} onOpen={vi.fn()} />);

    await userEvent.click(screen.getByText("references"));
    await userEvent.click(screen.getByText("references"));

    expect(screen.getByText("a.md")).toBeInTheDocument();
  });

  it("nests a group inside its folder rather than flattening it", () => {
    const nodes = buildTree([resource("a/b/deep.md", "id-deep")]);
    render(<FileTree nodes={nodes} openId={null} onOpen={vi.fn()} />);

    expect(screen.getAllByRole("group")).not.toHaveLength(0);
    expect(screen.getByText("deep.md")).toBeInTheDocument();
  });
});

describe("the file pane", () => {
  function mount(props: Partial<Parameters<typeof FilePane>[0]> = {}) {
    const onSave = vi.fn();
    const onDelete = vi.fn();
    render(
      <FilePane
        skillId="s-1"
        resource={resource("checklist.md", "r-1")}
        canEdit
        busy={false}
        onSave={onSave}
        onDelete={onDelete}
        {...props}
      />,
    );
    return { onSave, onDelete };
  }

  it("shows what the server holds until somebody types", () => {
    mount();

    expect(screen.getByTestId("rendered")).toHaveTextContent("# Body");
  });

  it("cannot save a file nobody has changed", () => {
    mount();

    expect(screen.getByRole("button", { name: "Save file" })).toBeDisabled();
  });

  it("saves the edited content and forgets the draft", async () => {
    const { onSave } = mount();

    await userEvent.click(screen.getByRole("button", { name: "Source" }));
    await userEvent.type(screen.getByLabelText("checklist.md source"), "!");
    await userEvent.click(screen.getByRole("button", { name: "Save file" }));

    expect(onSave).toHaveBeenCalledWith("# Body!");
    // The draft is cleared, so the button goes back to having nothing to do.
    expect(screen.getByRole("button", { name: "Save file" })).toBeDisabled();
  });

  it("offers a discard only once there is something to discard", async () => {
    mount();

    expect(screen.queryByRole("button", { name: "Discard" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Source" }));
    await userEvent.type(screen.getByLabelText("checklist.md source"), "!");

    expect(screen.getByRole("button", { name: "Discard" })).toBeInTheDocument();
  });

  it("throws the draft away on discard, back to what the server holds", async () => {
    mount();

    await userEvent.click(screen.getByRole("button", { name: "Source" }));
    await userEvent.type(screen.getByLabelText("checklist.md source"), "!");
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));

    expect(screen.getByLabelText("checklist.md source")).toHaveValue("# Body");
  });

  it("cannot be saved while a save is in flight", async () => {
    mount({ busy: true });

    await userEvent.click(screen.getByRole("button", { name: "Source" }));
    await userEvent.type(screen.getByLabelText("checklist.md source"), "!");

    expect(screen.getByRole("button", { name: "Save file" })).toBeDisabled();
  });

  it("shows no footer at all to somebody who may not edit", () => {
    mount({ canEdit: false });

    expect(screen.queryByRole("button", { name: "Save file" })).toBeNull();
  });

  it("says it is loading while the file has not arrived", () => {
    loaded.content = undefined;
    loaded.isLoading = true;
    mount();

    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });
});

describe("the new-file form", () => {
  function mount(props: Partial<Parameters<typeof NewFileForm>[0]> = {}) {
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    render(<NewFileForm busy={false} onCancel={onCancel} onSubmit={onSubmit} {...props} />);
    return { onSubmit, onCancel };
  }

  it("cannot be submitted without a path", () => {
    mount();

    expect(screen.getByRole("button", { name: "Add file" })).toBeDisabled();
  });

  it("says a folder is made by naming a file inside it", () => {
    // There is nothing else to create, and that is not obvious.
    mount();

    expect(screen.getByText(/A folder is made by naming a file inside it/)).toBeInTheDocument();
  });

  it("submits a trimmed path, a description and the body", async () => {
    const { onSubmit } = mount();

    await userEvent.type(screen.getByLabelText("Path"), "  references/a.md  ");
    await userEvent.type(screen.getByLabelText("Description"), "  What is in it  ");
    await userEvent.type(screen.getByLabelText("File contents"), "body");
    await userEvent.click(screen.getByRole("button", { name: "Add file" }));

    expect(onSubmit).toHaveBeenCalledWith({
      name: "references/a.md",
      description: "What is in it",
      content: "body",
    });
  });

  it("sends no description rather than an empty one", async () => {
    // `""` is a description the model would read as blank rather than absent.
    const { onSubmit } = mount();

    await userEvent.type(screen.getByLabelText("Path"), "a.md");
    await userEvent.click(screen.getByRole("button", { name: "Add file" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ description: null, content: "" }),
    );
  });

  it("cannot be submitted while one is in flight", async () => {
    mount({ busy: true });

    await userEvent.type(screen.getByLabelText("Path"), "a.md");

    expect(screen.getByRole("button", { name: "Add file" })).toBeDisabled();
  });

  it("cancels without submitting", async () => {
    const { onSubmit, onCancel } = mount();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onCancel).toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe("the upload button", () => {
  it("hands the picked files to the caller", async () => {
    const onPick = vi.fn();
    render(<UploadButton label="Add files" onPick={onPick} />);

    const file = new File(["x"], "a.md", { type: "text/markdown" });
    await userEvent.upload(screen.getByLabelText("Add files"), file);

    expect(onPick).toHaveBeenCalledWith([file]);
  });

  it("hands over a list rather than a FileList that may be null", async () => {
    // Every caller used to convert this itself, and every caller had to guess
    // what a dismissed picker looks like. It looks like this.
    const onPick = vi.fn();
    render(<UploadButton label="Add files" onPick={onPick} />);

    fireEvent.change(screen.getByLabelText("Add files"), { target: { files: [] } });

    expect(onPick).toHaveBeenCalledWith([]);
  });

  it("clears the input so the same file can be picked twice", async () => {
    // Without it, re-picking the file just corrected produces no change event.
    const onPick = vi.fn();
    render(<UploadButton label="Add files" onPick={onPick} />);
    const input = screen.getByLabelText("Add files") as HTMLInputElement;

    await userEvent.upload(input, new File(["x"], "a.md"));

    expect(input.value).toBe("");
  });

  it("asks for a directory when told to", () => {
    // The only way to pick a folder, and not in React's JSX types.
    render(<UploadButton label="Add a folder" directory onPick={vi.fn()} />);

    expect(screen.getByLabelText("Add a folder")).toHaveAttribute("webkitdirectory");
  });
});
