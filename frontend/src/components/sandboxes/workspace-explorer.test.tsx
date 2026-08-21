import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceExplorer, treeOf } from "./workspace-explorer";
import type { WorkspaceFile, WorkspaceFiles } from "@/lib/sandbox-workspaces-api";

const state = vi.hoisted(() => ({
  files: null as WorkspaceFiles | null,
  filesLoading: false,
  filesError: null as string | null,
  file: null as { path: string; content: string; truncated: boolean } | null,
  fileLoading: false,
  fileError: null as string | null,
  bytesUrl: null as string | null,
  bytesMediaType: "image/png" as string | null,
  bytesLoading: false,
  bytesError: null as string | null,
  downloaded: [] as [string, string][],
  downloadError: null as string | null,
}));

/**
 * The access the explorer builds, with its address left readable.
 *
 * What this test is about is the tree: which files a folder shows, what search
 * reaches, and that a click opens the viewer on the file that was clicked. How that
 * file then *renders* is `components/files`, tested once there rather than once per
 * surface - which is the whole point of there being one viewer.
 */
vi.mock("@/lib/workspace-files", () => ({
  workspaceFileAccess: (source: { id: string }, path: string) => ({
    id: source.id,
    path,
    textKey: ["text", path],
    bytesKey: ["bytes", path],
    download: () => {
      state.downloaded.push([source.id, path]);
      return Promise.resolve();
    },
  }),
}));

vi.mock("@/hooks", () => ({
  useWorkspaceFiles: () => ({
    files: state.files,
    isLoading: state.filesLoading,
    error: state.filesError,
  }),
  useFileText: () => ({
    file: state.file,
    isLoading: state.fileLoading,
    error: state.fileError,
  }),
  useFileBytes: () => ({
    url: state.bytesUrl,
    mediaType: state.bytesMediaType,
    isLoading: state.bytesLoading,
    error: state.bytesError,
  }),
  useFileActions: (access: { id: string; path: string }) => ({
    download: () => state.downloaded.push([access.id, access.path]),
    openInNewTab: () => {},
    error: state.downloadError,
  }),
}));

vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="rendered">{content}</div>
  ),
}));

function file(path: string, overrides: Partial<WorkspaceFile> = {}): WorkspaceFile {
  return { path, size: 128, is_dir: false, modified_at: null, ...overrides };
}

function listing(items: WorkspaceFile[], overrides: Partial<WorkspaceFiles> = {}): WorkspaceFiles {
  return {
    scope: "conversation",
    backend: "state",
    owner_label: "This conversation",
    items,
    total: items.length,
    bytes_total: 4096,
    unreadable_reason: null,
    ...overrides,
  };
}

beforeEach(() => {
  state.files = listing([
    file("/report.md"),
    file("/skills/code-review/SKILL.md"),
    file("/skills/code-review/checklist.md"),
    file("/chart.png"),
  ]);
  state.filesLoading = false;
  state.filesError = null;
  state.file = { path: "/report.md", content: "# Report", truncated: false };
  state.fileLoading = false;
  state.fileError = null;
  state.bytesUrl = "blob:chart";
  state.bytesMediaType = "image/png";
  state.bytesLoading = false;
  state.bytesError = null;
  state.downloaded = [];
  state.downloadError = null;
});

/**
 * One workspace, folder by folder.
 *
 * The listing carries every path, so a folder is a filter rather than a request -
 * which is also what makes search immediate and whole-tree. The two properties worth
 * pinning: walking in and out lands where you expect, and search is not scoped to
 * the folder on screen, because "where is that CSV" is the question this is opened
 * to answer.
 */
describe("the workspace explorer", () => {
  it("shows every level at once, open, rather than one folder at a time", () => {
    // The drill-down it replaces showed one level and a breadcrumb, so a workspace
    // whose only folder was `uploads` opened on a list of one row and hid every
    // file it held.
    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.getByText("skills")).toBeVisible();
    expect(screen.getByText("report.md")).toBeVisible();
    expect(screen.getByText("SKILL.md")).toBeVisible();
  });

  it("says whose files these are, and what they weigh", () => {
    // Under `agent` scope one workspace is shared, so somebody opens this and finds
    // a file they never created; a tree of paths with no statement of who can see
    // them is the wrong thing to hand somebody auditing it.
    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.getByText(/This conversation/)).toBeVisible();
    expect(screen.getByText(/4\.0 KB stored/)).toBeVisible();
  });

  it("says nothing about size for a workspace kept on a host", () => {
    // `bytes_total` is the stored document's size; for a container it is zero and
    // would read as an empty workspace.
    state.files = listing([file("/report.md")], { backend: "service", bytes_total: 0 });
    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.queryByText(/stored/)).toBeNull();
  });

  it("closes a folder, and opens it again", async () => {
    render(<WorkspaceExplorer workspaceId="w-1" />);
    const folder = () => screen.getByRole("treeitem", { name: /skills/ });

    expect(folder()).toHaveAttribute("aria-expanded", "true");

    await userEvent.click(screen.getByText("skills"));

    expect(folder()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("SKILL.md")).toBeNull();

    await userEvent.click(screen.getByText("skills"));

    expect(screen.getByText("SKILL.md")).toBeVisible();
  });

  it("indents each level, which is what says what is inside what", async () => {
    render(<WorkspaceExplorer workspaceId="w-1" />);

    const indent = (name: string) => screen.getByText(name).closest("button")!.style.paddingLeft;

    expect(indent("skills")).toBe("0.5rem");
    expect(indent("code-review")).toBe("1.25rem");
    expect(indent("SKILL.md")).toBe("2rem");
  });

  it("is a tree to a screen reader, not a list of buttons", async () => {
    // The meaning of a row is its left margin, and a margin is not something a
    // screen reader can read out.
    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.getByRole("tree")).toBeInTheDocument();
    expect(screen.getAllByRole("treeitem").length).toBeGreaterThan(3);
  });

  it("renders the file beside the tree rather than over it", async () => {
    // A dialog closes the list every time, and reading a workspace means reading
    // several files in turn - so the tree stays and the file renders next to it
    // (#1039). `FileViewer` is still what the flat "all files" list opens, where
    // one file is the whole errand.
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByRole("button", { name: "report.md" }));

    expect(await screen.findByTestId("rendered")).toHaveTextContent("# Report");
    expect(screen.queryByRole("dialog")).toBeNull();
    // The tree is still there, which is the whole reason for the shape.
    expect(screen.getByRole("button", { name: "chart.png" })).toBeVisible();
  });

  it("offers markdown as source, and offers nothing to toggle on an image", async () => {
    // The toggle exists where there are two renderings to choose between. On a PNG
    // it would offer to show the same thing twice.
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByRole("button", { name: "report.md" }));
    await userEvent.click(screen.getByRole("button", { name: "Source" }));

    expect(screen.getByRole("button", { name: "Preview" })).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(screen.getByRole("button", { name: "chart.png" }));

    expect(screen.queryByRole("button", { name: /Source|Preview/ })).toBeNull();
  });

  it("moves between two files in one click", async () => {
    render(<WorkspaceExplorer workspaceId="w-1" />);
    await userEvent.click(screen.getByRole("button", { name: "report.md" }));
    await screen.findByTestId("rendered");

    await userEvent.click(screen.getByRole("button", { name: "chart.png" }));

    expect(screen.getByRole("button", { name: "chart.png" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByRole("button", { name: "report.md" })).toHaveAttribute(
      "aria-current",
      "false",
    );
  });

  it("offers a download without opening the file first", async () => {
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByRole("button", { name: "Download /report.md" }));

    expect(state.downloaded).toEqual([["w-1", "/report.md"]]);
  });

  it("explains a host that keeps nothing on disk instead of alarming somebody", () => {
    state.files = listing([], { unreadable_reason: "This host keeps no workspaces on disk." });
    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.getByText("This host keeps no workspaces on disk.")).toBeVisible();
    expect(screen.getByText(/Nothing could be listed here/)).toBeVisible();
  });

  it("says a folder is empty when it is", () => {
    state.files = listing([]);
    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.getByText("This folder is empty.")).toBeVisible();
  });

  it("waits without claiming the workspace is empty", () => {
    state.files = null;
    state.filesLoading = true;
    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.queryByText(/This folder is empty/)).toBeNull();
  });

  it("reports a listing that failed", () => {
    state.files = null;
    state.filesError = "That workspace could not be read";
    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.getByText("That workspace could not be read")).toBeVisible();
  });

  it("reads a file with no measured size as unmeasured", () => {
    state.files = listing([file("/report.md", { size: null })]);
    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.getByText("—")).toBeVisible();
  });

  it("reads sizes in the units a person uses", () => {
    state.files = listing([
      file("/small.txt", { size: 12 }),
      file("/mid.csv", { size: 2048 }),
      file("/big.bin", { size: 2_097_152 }),
    ]);
    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.getByText("12 B")).toBeVisible();
    expect(screen.getByText("2.0 KB")).toBeVisible();
    expect(screen.getByText("2.0 MB")).toBeVisible();
  });
});

/**
 * The tree itself, which the component only ever renders.
 *
 * Worth its own tests because the awkward cases are all off-screen: a folder the
 * listing never named, a directory entry that it did, and the order two readers of
 * the same workspace have to see.
 */
describe("the tree built from the paths", () => {
  const paths = (nodes: ReturnType<typeof treeOf>): string[] =>
    nodes.flatMap((node) => [node.path, ...paths(node.children)]);

  it("invents a folder the listing never named", () => {
    // A host that returns `uploads/x.pdf` and no directory row still has an
    // `uploads`, and a tree built only from `is_dir` rows would hide the file
    // under a folder it never drew.
    const tree = treeOf([file("/uploads/x.pdf")]);

    expect(tree).toHaveLength(1);
    expect(tree[0]!.isDir).toBe(true);
    expect(tree[0]!.name).toBe("uploads");
    expect(tree[0]!.children.map((child) => child.name)).toEqual(["x.pdf"]);
  });

  it("uses the directory row where the listing includes one, not two folders", () => {
    const tree = treeOf([file("/a", { is_dir: true }), file("/a/one.txt")]);

    expect(paths(tree)).toEqual(["a", "/a/one.txt"]);
  });

  it("nests as deep as the paths do", () => {
    const tree = treeOf([file("/skills/deploy/run.sh")]);

    expect(paths(tree)).toEqual(["skills", "skills/deploy", "/skills/deploy/run.sh"]);
  });

  it("puts folders above files, each alphabetical", () => {
    // The order every file manager uses, and the one that puts what can be opened
    // where a reader looks first.
    const tree = treeOf([file("/z.txt"), file("/a.txt"), file("/m/one.txt")]);

    expect(tree.map((node) => node.name)).toEqual(["m", "a.txt", "z.txt"]);
  });

  it("keeps two folders apart", () => {
    const tree = treeOf([file("/a/one.txt"), file("/b/two.txt")]);

    expect(tree.map((node) => node.name)).toEqual(["a", "b"]);
    expect(tree[0]!.children.map((child) => child.path)).toEqual(["/a/one.txt"]);
  });
});

describe("the height it occupies", () => {
  it("fills the page rather than being as tall as its content", () => {
    // Two panes 300px tall under 600px of empty page: `min-h-[24rem]` was the only
    // height in the chain and nothing above it passed one down. Every link has to
    // carry `min-h-0`, or a flex child's default minimum is its content and the
    // panes grow the page instead of scrolling inside it.
    const { container } = render(<WorkspaceExplorer workspaceId="w-1" />);

    const root = container.firstElementChild!;

    expect(root.className).toContain("flex-1");
    expect(root.className).toContain("min-h-0");

    const grid = container.querySelector(".grid")!;

    expect(grid.className).toContain("flex-1");
    expect(grid.className).toContain("min-h-0");
  });

  it("scrolls each pane inside its own share", () => {
    // A workspace with two hundred files scrolls the list, not the page - and the
    // reader's file stays where they left it.
    const { container } = render(<WorkspaceExplorer workspaceId="w-1" />);
    const [tree, reader] = [...container.querySelectorAll(".grid > div")];

    expect(tree!.className).toContain("overflow-y-auto");
    expect(reader!.className).toContain("overflow-hidden");
  });
});

describe("which folders start open", () => {
  it("opens every folder of a small workspace", () => {
    // A workspace nests three deep at most and usually holds a handful of files, so
    // a tree that starts closed hides the only thing on the page - `uploads` was
    // one click away from being the only visible row.
    state.files = listing([file("/uploads/ksionszka.pdf"), file("/skills/deploy/run.sh")]);

    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.getByText("ksionszka.pdf")).toBeVisible();
    expect(screen.getByText("run.sh")).toBeVisible();
  });

  it("opens only the top level of a workspace too large to draw whole", () => {
    // A thousand rows rendered at once is a different failure from a hidden one.
    state.files = listing([
      ...Array.from({ length: 201 }, (_, n) => file(`/uploads/scan-${n}.pdf`)),
      file("/uploads/deep/one.txt"),
    ]);

    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.getByText("deep")).toBeVisible();
    expect(screen.queryByText("one.txt")).toBeNull();
  });

  it("shows an empty folder as an empty folder rather than as nothing", () => {
    // A host that lists a directory row with nothing inside it: the drill-down
    // answered "This folder is empty" on a page with no other content, which reads
    // as a broken workspace.
    state.files = listing([file("/uploads", { is_dir: true }), file("/report.md")]);

    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.getByText("uploads")).toBeVisible();
    expect(screen.getByText("report.md")).toBeVisible();
  });
});
