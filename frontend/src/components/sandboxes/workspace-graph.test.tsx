import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspaceGraph } from "./workspace-graph";
import { WikiCanvas } from "./wiki-canvas";
import { buildWikiGraph, parseWikiPage } from "@/lib/wiki-graph";
import { listProjectFiles } from "@/lib/projects-api";
import { readFileText } from "@/lib/workspace-files";
import type { WorkspaceFiles } from "@/lib/sandbox-workspaces-api";

vi.mock("@/hooks/use-resolved-theme", () => ({ useResolvedTheme: () => "light" }));

vi.mock("@/lib/projects-api", () => ({ listProjectFiles: vi.fn() }));
vi.mock("@/lib/workspace-files", () => ({
  readFileText: vi.fn(),
  textKey: (_source: unknown, path: string) => ["text", path],
  bytesKey: (_source: unknown, path: string) => ["bytes", path],
  workspaceFileAccess: (_source: unknown, path: string) => ({ path }),
}));
vi.mock("@/components/files", () => ({
  FileViewer: ({ file, onClose }: { file: { path: string }; onClose: () => void }) => (
    <div role="dialog" aria-label={file.path}>
      <button onClick={onClose}>Close viewer</button>
    </div>
  ),
}));

const file = (path: string) => ({ path, size: 100, is_dir: false, modified_at: null });
const listing: WorkspaceFiles = {
  items: [file("a.md"), file("b.md"), file("c.md")],
  total: 3,
  bytes_total: 300,
  scope: "project",
  backend: "state",
  owner_label: "Wiki",
  unreadable_reason: null,
  truncated: false,
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listProjectFiles).mockResolvedValue(listing);
  vi.mocked(readFileText).mockImplementation(async (_, path) => ({
    content:
      path === "a.md"
        ? "---\ntitle: Alpha\ntags: [research]\naliases: First\n---\n[[b]] [[missing]]"
        : path === "b.md"
          ? "# Beta"
          : "# Gamma",
    truncated: false,
  }));
});

function mount(editor = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const result = render(
    <QueryClientProvider client={client}>
      <WorkspaceGraph
        source={{ kind: "project", id: "p" }}
        onClose={vi.fn()}
        renderEditor={editor ? (path) => <button>Edit {path}</button> : undefined}
      />
    </QueryClientProvider>,
  );
  return { ...result, client };
}

describe("live workspace graph", () => {
  it("omits dangling edge endpoints instead of crashing navigation", () => {
    const graph = buildWikiGraph([parseWikiPage("a.md", "# A")]);
    graph.edges = [
      { source: "deleted", target: "a.md" },
      { source: "a.md", target: "deleted" },
    ];
    const { container } = render(
      <WikiCanvas graph={graph} selected={null} visible={new Set(["a.md"])} onSelect={vi.fn()} />,
    );
    expect(container.querySelectorAll(".react-flow__edge")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "A" })).toBeVisible();
  });
  it("browses links and backlinks, filters by metadata and opens the existing viewer", async () => {
    mount(true);
    await screen.findByText("3 notes · 1 link");
    const user = userEvent.setup();
    fireEvent.click(screen.getAllByRole("button", { name: "Alpha" })[0]!);
    expect(screen.getByText("Links to")).toBeVisible();
    expect(screen.getByText("missing — missing from this scan")).toBeVisible();
    expect(screen.getByRole("button", { name: "Edit a.md" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Notes" }));
    const gamma = screen
      .getAllByRole("button", { name: "Gamma" })
      .find((entry) => entry.tagName === "BUTTON");
    if (!gamma) throw new Error("Note list button missing");
    await user.click(gamma);
    fireEvent.click(screen.getAllByRole("button", { name: "Alpha" })[0]!);
    await user.click(screen.getByRole("button", { name: "b.md" }));
    expect(screen.getByRole("button", { name: "a.md" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Open note" }));
    expect(await screen.findByRole("dialog", { name: "b.md" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Close viewer" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.type(screen.getByRole("textbox"), "#research");
    expect(screen.getAllByRole("button", { name: "Alpha" })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Gamma" })).not.toBeInTheDocument();
    await user.clear(screen.getByRole("textbox"));
    await user.type(screen.getByRole("textbox"), "absent");
    expect(screen.getByText("No matching notes")).toBeVisible();
  });

  it("starts fullscreen, keeps navigation available and restores the shell on exit", async () => {
    const { container } = mount();
    await screen.findByText("3 notes · 1 link");
    expect(container.querySelector("[data-expanded]")).toHaveAttribute("data-expanded", "true");
    expect(document.body.style.overflow).toBe("hidden");
    await userEvent.click(screen.getByRole("button", { name: "Notes" }));
    await userEvent.click(screen.getAllByRole("button", { name: "Alpha" }).at(-1)!);
    expect(screen.getByRole("complementary", { name: "Note details" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Close note details" }));
    expect(screen.queryByRole("complementary", { name: "Note details" })).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(container.querySelector("[data-expanded]")).toHaveAttribute("data-expanded", "false");
    expect(document.body.style.overflow).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Alpha" }));
    fireEvent.click(container.querySelector(".react-flow__pane")!);
    expect(screen.queryByRole("complementary", { name: "Note details" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset view" }));
  });

  it("refreshes changed notes and removes deleted notes from the graph", async () => {
    mount();
    await screen.findByText("3 notes · 1 link");
    vi.mocked(listProjectFiles).mockResolvedValue({ ...listing, items: [file("a.md")] });
    vi.mocked(readFileText).mockResolvedValue({ content: "# New title", truncated: false });
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("1 note · 0 links");
    expect(screen.queryByRole("button", { name: "Beta" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "New title" })).toHaveLength(1);
  });

  it("labels an incomplete graph and invalid metadata rather than claiming a complete wiki", async () => {
    vi.mocked(listProjectFiles).mockResolvedValue({
      ...listing,
      truncated: true,
      items: [file("a.md"), file("failed.md"), { ...file("large.md"), size: 999999 }],
    });
    vi.mocked(readFileText).mockImplementation(async (_, path) => {
      if (path === "failed.md") throw new Error("unreadable");
      return { content: "---\ntitle: [broken\n---\n# Body", truncated: false };
    });
    mount();
    await screen.findByText("1 note · 0 links");
    expect(screen.getByRole("alert")).toHaveTextContent("Invalid YAML frontmatter");
    await userEvent.click(screen.getByText("This graph is incomplete"));
    expect(screen.getByText("Skipped: large.md")).toBeVisible();
    expect(screen.getByText("Could not read: failed.md")).toBeVisible();
  });

  it("hides cached notes if a refresh loses access, and permits retry", async () => {
    mount();
    await screen.findByText("3 notes · 1 link");
    vi.mocked(listProjectFiles).mockRejectedValueOnce(new Error("denied"));
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not read this workspace");
    expect(screen.queryByText("3 notes · 1 link")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("3 notes · 1 link");
  });

  it("distinguishes an empty workspace from a read failure", async () => {
    vi.mocked(listProjectFiles).mockResolvedValue({ ...listing, items: [] });
    mount();
    expect(await screen.findByText(/Add Markdown notes/)).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(within(screen.getByRole("status")).getByText(/Refreshes every/)).toBeVisible();
  });
});
