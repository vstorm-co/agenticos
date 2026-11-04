import { beforeEach, describe, expect, it, vi } from "vitest";
import { WIKI_RELATION_LIMITS } from "./wiki-graph";
import { readWikiWorkspace, WIKI_LIMITS } from "./wiki-workspace";
import { listProjectFiles } from "./projects-api";
import { readWorkspaceFiles, type WorkspaceFiles } from "./sandbox-workspaces-api";
import { readConversationWorkspace } from "./conversation-workspace-api";
import { listLocalFiles } from "./desktop/commands";
import { readFileText } from "./workspace-files";

vi.mock("./projects-api", () => ({ listProjectFiles: vi.fn() }));
vi.mock("./sandbox-workspaces-api", () => ({ readWorkspaceFiles: vi.fn() }));
vi.mock("./conversation-workspace-api", () => ({ readConversationWorkspace: vi.fn() }));
vi.mock("./desktop/commands", () => ({ listLocalFiles: vi.fn() }));
vi.mock("./workspace-files", () => ({ readFileText: vi.fn() }));
const signal = () => new AbortController().signal;
const file = (path: string, size: number | null = 100) => ({
  path,
  size,
  is_dir: false,
  modified_at: null,
});
const listing = (items = [file("a.md"), file("b.md")]): WorkspaceFiles => ({
  scope: "project",
  backend: "state",
  owner_label: "Wiki",
  items,
  total: items.length,
  bytes_total: 200,
  unreadable_reason: null,
  truncated: false,
});

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listProjectFiles).mockResolvedValue(listing());
  vi.mocked(readFileText).mockImplementation(async (_, path) => ({
    content: path === "a.md" ? "[[b]]" : "# B",
    truncated: false,
  }));
});

describe("wiki workspace reads", () => {
  it("rescans contents and the listing so edits, additions and deletions need no agent rendering", async () => {
    const source = { kind: "project", id: "p" } as const;
    expect((await readWikiWorkspace(source, signal())).edges).toHaveLength(1);
    vi.mocked(listProjectFiles).mockResolvedValue(listing([file("a.md"), file("c.md")]));
    vi.mocked(readFileText).mockResolvedValue({ content: "[[c]]", truncated: false });
    const updated = await readWikiWorkspace(source, signal());
    expect(updated.pages.map((page) => page.path)).toEqual(["a.md", "c.md"]);
    expect(updated.edges).toEqual([{ source: "a.md", target: "c.md" }]);
  });

  it("uses each source's own authorization path and never uploads local files", async () => {
    vi.mocked(readWorkspaceFiles).mockResolvedValue(listing());
    vi.mocked(readConversationWorkspace).mockResolvedValue({
      ...listing(),
      items: [],
      bytes_limit: null,
    });
    vi.mocked(listLocalFiles).mockResolvedValue([
      { path: "a.md", size: 4, is_dir: false, modified: null },
    ]);
    await readWikiWorkspace({ kind: "workspace", id: "w" }, signal());
    await readWikiWorkspace({ kind: "conversation", id: "c" }, signal());
    await readWikiWorkspace({ kind: "local", root: "/granted" }, signal());
    expect(readWorkspaceFiles).toHaveBeenCalledWith("w");
    expect(readConversationWorkspace).toHaveBeenCalledWith("c");
    expect(listLocalFiles).toHaveBeenCalledWith("/granted");
    expect(readFileText).toHaveBeenLastCalledWith({ kind: "local", root: "/granted" }, "a.md");
  });

  it("bounds pages, bytes and concurrency, and says which notes are missing", async () => {
    const items = Array.from({ length: WIKI_LIMITS.pages + 1 }, (_, i) =>
      file(`${String(i).padStart(3, "0")}.md`),
    );
    items.push(file("huge.md", WIKI_LIMITS.fileBytes + 1), file("image.png"), {
      ...file("folder.md"),
      is_dir: true,
    });
    vi.mocked(listProjectFiles).mockResolvedValue({ ...listing(items), truncated: true });
    let active = 0,
      peak = 0;
    vi.mocked(readFileText).mockImplementation(async () => {
      active++;
      peak = Math.max(peak, active);
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
      active--;
      return { content: "", truncated: false };
    });
    const graph = await readWikiWorkspace({ kind: "project", id: "p" }, signal());
    expect(graph.pages).toHaveLength(WIKI_LIMITS.pages);
    expect(graph.skipped).toEqual(["200.md", "huge.md"]);
    expect(graph.truncated).toBe(true);
    expect(peak).toBe(4);
    vi.mocked(listProjectFiles).mockResolvedValue(
      listing(Array.from({ length: 35 }, (_, i) => file(`${i}.md`, null))),
    );
    const limited = await readWikiWorkspace({ kind: "project", id: "p" }, signal());
    expect(limited.pages).toHaveLength(32);
    expect(limited.skipped).toHaveLength(3);
  });

  it("does not turn failed or truncated reads into empty successful notes", async () => {
    vi.mocked(listProjectFiles).mockResolvedValue(
      listing([file("failed.md"), file("truncated.md"), file("grew.md"), file("ok.md")]),
    );
    vi.mocked(readFileText).mockImplementation(async (_, path) => {
      if (path === "failed.md") throw new Error("read failed");
      return {
        content: path === "grew.md" ? "é".repeat(WIKI_LIMITS.fileBytes) : "ok",
        truncated: path === "truncated.md",
      };
    });
    const graph = await readWikiWorkspace({ kind: "project", id: "p" }, signal());
    expect(graph.pages.map((page) => page.path)).toEqual(["ok.md"]);
    expect(graph.failed).toEqual(["failed.md"]);
    expect(graph.skipped).toEqual(["grew.md", "truncated.md"]);
  });

  it("propagates a failed listing, revoked access and cancellation", async () => {
    vi.mocked(listProjectFiles).mockRejectedValueOnce(new Error("offline"));
    await expect(readWikiWorkspace({ kind: "project", id: "p" }, signal())).rejects.toThrow(
      "offline",
    );
    vi.mocked(listProjectFiles).mockResolvedValueOnce({
      ...listing(),
      unreadable_reason: "unavailable",
    });
    await expect(readWikiWorkspace({ kind: "project", id: "p" }, signal())).rejects.toThrow(
      "unavailable",
    );
    vi.mocked(readFileText).mockRejectedValue({ status: 403 });
    await expect(readWikiWorkspace({ kind: "project", id: "p" }, signal())).rejects.toEqual({
      status: 403,
    });
    const controller = new AbortController();
    controller.abort();
    await expect(
      readWikiWorkspace({ kind: "project", id: "p" }, controller.signal),
    ).rejects.toThrow();
    const during = new AbortController();
    vi.mocked(readFileText).mockImplementation(async () => {
      during.abort();
      return { content: "", truncated: false };
    });
    await expect(readWikiWorkspace({ kind: "project", id: "p" }, during.signal)).rejects.toThrow();
  });
});

it("keeps the incomplete-listing flag for conversation workspaces", async () => {
  vi.mocked(readConversationWorkspace).mockResolvedValue({
    ...listing(),
    items: [],
    bytes_limit: null,
    truncated: true,
  });
  const graph = await readWikiWorkspace({ kind: "conversation", id: "c" }, signal());
  expect(graph.truncated).toBe(true);
});

it("stops retaining relationships at the graph-wide budget and warns of the partial graph", async () => {
  vi.mocked(listProjectFiles).mockResolvedValue(
    listing(Array.from({ length: 12 }, (_, i) => file(`${i}.md`))),
  );
  vi.mocked(readFileText).mockResolvedValue({
    content: Array.from({ length: 256 }, (_, i) => `[[${i}]]`).join(" "),
    truncated: false,
  });
  const graph = await readWikiWorkspace({ kind: "project", id: "p" }, signal());
  expect(graph.pages.reduce((sum, page) => sum + page.links.length, 0)).toBe(
    WIKI_RELATION_LIMITS.graph,
  );
  expect(graph.truncated).toBe(true);
});

it("allocates the shared relationship budget in path order regardless of read completion order", async () => {
  const files = Array.from({ length: 12 }, (_, i) => file(`${String(i).padStart(2, "0")}.md`));
  vi.mocked(listProjectFiles).mockResolvedValue(listing(files));
  const scan = async (reverse: boolean) => {
    vi.mocked(readFileText).mockImplementation(async (_, path) => {
      const index = Number.parseInt(path, 10);
      await new Promise<void>((resolve) =>
        setTimeout(resolve, reverse ? (3 - (index % 4)) * 2 : (index % 4) * 2),
      );
      return {
        content: Array.from({ length: 256 }, (_, i) => `[[target-${i}]]`).join(" "),
        truncated: false,
      };
    });
    return readWikiWorkspace({ kind: "project", id: "p" }, signal());
  };
  const forward = await scan(false);
  const reverse = await scan(true);
  expect(reverse.pages).toEqual(forward.pages);
  expect(reverse.edges).toEqual(forward.edges);
  expect(reverse.unresolved).toEqual(forward.unresolved);
  expect(reverse.pages[0]?.links).toHaveLength(256);
  expect(reverse.pages[8]?.links).toHaveLength(0);
});

it("shares a metadata budget across notes and reports a partial graph", async () => {
  vi.mocked(listProjectFiles).mockResolvedValue(
    listing(Array.from({ length: 40 }, (_, i) => file(`${i}.md`))),
  );
  vi.mocked(readFileText).mockResolvedValue({
    content: `---\naliases: ${JSON.stringify(Array.from({ length: 128 }, (_, i) => `alias${i}`))}\n---`,
    truncated: false,
  });
  const graph = await readWikiWorkspace({ kind: "project", id: "p" }, signal());
  expect(
    graph.pages.reduce((count, page) => count + page.aliases.length + page.tags.length, 0),
  ).toBe(4096);
  expect(graph.truncated).toBe(true);
});

it("enforces the byte budget when files grow after their listing", async () => {
  vi.mocked(listProjectFiles).mockResolvedValue(
    listing(Array.from({ length: 33 }, (_, i) => file(`${String(i).padStart(2, "0")}.md`, 1))),
  );
  vi.mocked(readFileText).mockResolvedValue({
    content: "a".repeat(WIKI_LIMITS.fileBytes),
    truncated: false,
  });
  const graph = await readWikiWorkspace({ kind: "project", id: "p" }, signal());
  expect(graph.pages).toHaveLength(32);
  expect(graph.skipped).toEqual(["32.md"]);
});
