import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceExplorer, levelAt } from "./workspace-explorer";
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

vi.mock("@/hooks", () => ({
  useWorkspaceFiles: () => ({
    files: state.files,
    isLoading: state.filesLoading,
    error: state.filesError,
  }),
  useWorkspaceFileText: () => ({
    file: state.file,
    isLoading: state.fileLoading,
    error: state.fileError,
  }),
  useWorkspaceFileBytes: () => ({
    url: state.bytesUrl,
    mediaType: state.bytesMediaType,
    isLoading: state.bytesLoading,
    error: state.bytesError,
  }),
  downloadWorkspaceFile: (source: { kind: string; id: string }, path: string) => {
    state.downloaded.push([source.id, path]);
    return Promise.resolve();
  },
  useFileDownload: (source: { kind: string; id: string }) => ({
    download: (path: string) => state.downloaded.push([source.id, path]),
    error: state.downloadError,
  }),
}));

vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="rendered">{content}</div>
  ),
}));

function file(path: string, overrides: Partial<WorkspaceFile> = {}): WorkspaceFile {
  return { path, size: 128, is_dir: false, ...overrides };
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
  it("shows the files and folders at the root, not every path at once", () => {
    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.getByText("skills")).toBeVisible();
    expect(screen.getByText("report.md")).toBeVisible();
    expect(screen.queryByText("SKILL.md")).toBeNull();
  });

  it("says whose files these are, and what they weigh", () => {
    // Under `agent` scope one workspace is shared, so somebody opens this and finds
    // a file they never created; a tree of paths with no statement of who can see
    // them is the wrong thing to hand somebody auditing it.
    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.getByText(/This conversation/)).toBeVisible();
    expect(screen.getByText(/4 KiB stored/)).toBeVisible();
  });

  it("says nothing about size for a workspace kept on a host", () => {
    // `bytes_total` is the stored document's size; for a container it is zero and
    // would read as an empty workspace.
    state.files = listing([file("/report.md")], { backend: "service", bytes_total: 0 });
    render(<WorkspaceExplorer workspaceId="w-1" />);

    expect(screen.queryByText(/stored/)).toBeNull();
  });

  it("walks into a folder", async () => {
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByText("skills"));
    await userEvent.click(screen.getByText("code-review"));

    expect(screen.getByText("SKILL.md")).toBeVisible();
    expect(screen.getByText("checklist.md")).toBeVisible();
  });

  it("walks back out from the breadcrumb", async () => {
    render(<WorkspaceExplorer workspaceId="w-1" />);
    await userEvent.click(screen.getByText("skills"));

    await userEvent.click(screen.getByRole("button", { name: "All files" }));

    expect(screen.getByText("report.md")).toBeVisible();
  });

  it("walks back up to a middle folder from the breadcrumb", async () => {
    // Two deep is where a back button stops being enough: the useful move is often
    // to the folder above rather than to the root.
    render(<WorkspaceExplorer workspaceId="w-1" />);
    await userEvent.click(screen.getByText("skills"));
    await userEvent.click(screen.getByText("code-review"));

    await userEvent.click(screen.getByRole("button", { name: "skills" }));

    expect(screen.getByText("code-review")).toBeVisible();
    expect(screen.queryByText("SKILL.md")).toBeNull();
  });

  it("searches every folder, not the one on screen", async () => {
    // Making somebody walk the tree to ask "where is that file" is the same failure
    // a flat list has in the other direction.
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.type(screen.getByLabelText("Search files by name"), "checklist");

    expect(screen.getByText("/skills/code-review/checklist.md")).toBeVisible();
    expect(screen.queryByText("report.md")).toBeNull();
  });

  it("says when a search matched nothing rather than showing an empty grid", async () => {
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.type(screen.getByLabelText("Search files by name"), "invoice");

    expect(screen.getByText(/Nothing in this workspace matches/)).toBeVisible();
  });

  it("opens a file into the viewer, named by its whole path", async () => {
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByRole("button", { name: "report.md" }));

    expect(await screen.findByRole("dialog")).toBeVisible();
    expect(screen.getByTestId("rendered")).toHaveTextContent("# Report");
    expect(screen.getByText("/report.md")).toBeVisible();
  });

  it("shows markdown as source when that is what somebody wants", async () => {
    // Both are the file: the prose is what a report means, and the characters are
    // what a prompt or a spec means.
    render(<WorkspaceExplorer workspaceId="w-1" />);
    await userEvent.click(screen.getByRole("button", { name: "report.md" }));

    await userEvent.click(await screen.findByRole("tab", { name: "Source" }));

    expect(screen.queryByTestId("rendered")).toBeNull();
    expect(screen.getByText("# Report")).toBeVisible();
  });

  it("closes it again", async () => {
    render(<WorkspaceExplorer workspaceId="w-1" />);
    await userEvent.click(screen.getByRole("button", { name: "report.md" }));
    await screen.findByRole("dialog");

    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("shows a PDF in the browser's own viewer", async () => {
    // An iframe rather than an image: it is the element every browser routes to its
    // PDF viewer, and that viewer never gets this page's DOM.
    state.bytesMediaType = "application/pdf";
    state.files = listing([file("/report.pdf")]);
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByRole("button", { name: "report.pdf" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog.querySelector("iframe")).toHaveAttribute("title", "/report.pdf");
  });

  it("previews an image as a picture", async () => {
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByRole("button", { name: "chart.png" }));

    expect(await screen.findByRole("img", { name: "/chart.png" })).toHaveAttribute(
      "src",
      "blob:chart",
    );
  });

  it("offers the download when the server did not serve it as something showable", async () => {
    // Whatever the suffix suggested. A broken `<img>` with nothing saying why is the
    // worst of the three answers.
    state.bytesMediaType = "application/octet-stream";
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByRole("button", { name: "chart.png" }));

    expect(await screen.findByText(/serves it as a file/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: /Download it$/ }));
    expect(state.downloaded).toEqual([["w-1", "/chart.png"]]);
  });

  it("offers a download without opening the file first", async () => {
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByRole("button", { name: "Download /report.md" }));

    expect(state.downloaded).toEqual([["w-1", "/report.md"]]);
  });

  it("offers a download when a file cannot be shown as text", async () => {
    // A binary on a container-backed host is refused by the API, and "it failed" with
    // no way forward is a worse answer than "here it is, as a file".
    state.fileError = "This host can only read text";
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByRole("button", { name: "report.md" }));
    await userEvent.click(await screen.findByRole("button", { name: /Download it$/ }));

    expect(state.downloaded).toEqual([["w-1", "/report.md"]]);
  });

  it("offers the download from the viewer for a file it is already showing", async () => {
    render(<WorkspaceExplorer workspaceId="w-1" />);
    await userEvent.click(screen.getByRole("button", { name: "report.md" }));

    await userEvent.click(await screen.findByRole("button", { name: "Download" }));

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

  it("reports an image that could not be fetched", async () => {
    state.bytesUrl = null;
    state.bytesError = "Those bytes could not be read";
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByRole("button", { name: "chart.png" }));

    expect(await screen.findByText("Those bytes could not be read")).toBeVisible();
  });

  it("draws no picture before the bytes arrive", async () => {
    state.bytesUrl = null;
    state.bytesLoading = true;
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByRole("button", { name: "chart.png" }));

    expect(screen.queryByRole("img")).toBeNull();
  });

  it("draws nothing for an image that answered with neither bytes nor an error", async () => {
    state.bytesUrl = null;
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByRole("button", { name: "chart.png" }));

    await waitFor(() => expect(screen.queryByRole("img")).toBeNull());
  });

  it("draws nothing for a text file that answered with neither", async () => {
    state.file = null;
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByRole("button", { name: "report.md" }));

    await screen.findByRole("dialog");
    expect(screen.queryByTestId("rendered")).toBeNull();
  });

  it("waits without claiming a text file is empty", async () => {
    state.file = null;
    state.fileLoading = true;
    render(<WorkspaceExplorer workspaceId="w-1" />);

    await userEvent.click(screen.getByRole("button", { name: "report.md" }));

    await screen.findByRole("dialog");
    expect(screen.queryByTestId("rendered")).toBeNull();
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
    expect(screen.getByText("2 KiB")).toBeVisible();
    expect(screen.getByText("2.0 MiB")).toBeVisible();
  });
});

/**
 * The tree walk itself, which the component only ever renders.
 *
 * Worth its own tests because the awkward cases are all off-screen: a directory entry
 * the listing includes, a path deeper than the folder being shown, and a sibling
 * folder that must not leak into it.
 */
describe("what sits inside one folder", () => {
  it("names a folder once, however many files it holds", () => {
    const level = levelAt([file("/a/one.txt"), file("/a/two.txt")], []);

    expect(level.folders).toEqual(["a"]);
    expect(level.files).toEqual([]);
  });

  it("keeps a sibling folder out of the one being shown", () => {
    const level = levelAt([file("/a/one.txt"), file("/b/two.txt")], ["a"]);

    expect(level.files.map((entry) => entry.path)).toEqual(["/a/one.txt"]);
  });

  it("treats a directory entry as a folder rather than as a file", () => {
    // The API lists directories, and one rendered as a file is a tile that opens
    // nothing.
    const level = levelAt([file("/a", { is_dir: true }), file("/a/one.txt")], []);

    expect(level.folders).toEqual(["a"]);
    expect(level.files).toEqual([]);
  });

  it("ignores a path shallower than the folder being shown", () => {
    const level = levelAt([file("/top.txt")], ["a"]);

    expect(level).toEqual({ folders: [], files: [] });
  });

  it("sorts both, so the same workspace reads the same way twice", () => {
    const level = levelAt([file("/z.txt"), file("/a.txt"), file("/m/one.txt")], []);

    expect(level.folders).toEqual(["m"]);
    expect(level.files.map((entry) => entry.path)).toEqual(["/a.txt", "/z.txt"]);
  });
});
