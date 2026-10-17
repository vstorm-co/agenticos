import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { compareFlat, WorkspaceBrowser } from "./workspace-browser";
import type { FlatFile } from "@/lib/sandbox-workspaces-api";
import type {
  FlatFileList,
  WorkspaceFileContent,
  WorkspaceFiles,
} from "@/lib/sandbox-workspaces-api";

const state = vi.hoisted(() => ({
  files: null as WorkspaceFiles | null,
  filesLoading: false,
  filesError: null as string | null,
  opened: [] as (string | null)[],
  file: null as WorkspaceFileContent | null,
  fileLoading: false,
  fileError: null as string | null,
  read: [] as (string | null)[],
  flat: null as FlatFileList | null,
  flatLoading: false,
  flatError: null as string | null,
  flatAsked: [] as boolean[],
  downloaded: [] as [string, string][],
  downloadError: null as string | null,
}));

vi.mock("@/lib/workspace-files", async (importOriginal) => ({
  documentName: (await importOriginal<typeof import("@/lib/workspace-files")>()).documentName,
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
  useAllWorkspaceFiles: (enabled: boolean) => {
    state.flatAsked.push(enabled);
    return { listing: state.flat, isLoading: state.flatLoading, error: state.flatError };
  },
  useWorkspaceFiles: (id: string | null) => {
    state.opened.push(id);
    return { files: state.files, isLoading: state.filesLoading, error: state.filesError };
  },
  useFileActions: (access: { id: string; path: string }) => ({
    download: () => state.downloaded.push([access.id, access.path]),
    openInNewTab: () => {},
    error: state.downloadError,
  }),
  useFileText: (access: { path: string }) => {
    state.read.push(access.path);
    return { file: state.file, isLoading: state.fileLoading, error: state.fileError };
  },
  useFileBytes: () => ({
    url: null,
    mediaType: null,
    isLoading: false,
    error: null,
  }),
}));

vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="rendered">{content}</div>
  ),
}));

function files(overrides: Partial<WorkspaceFiles> = {}): WorkspaceFiles {
  return {
    unreadable_reason: null,
    truncated: false,
    scope: "conversation",
    backend: "state",
    owner_label: "This conversation",
    items: [{ path: "/uploads/report.csv", size: 128, is_dir: false, modified_at: null }],
    total: 1,
    bytes_total: 1_048_576,
    ...overrides,
  };
}

beforeEach(() => {
  state.files = files();
  state.filesLoading = false;
  state.filesError = null;
  state.opened = [];
  state.file = { path: "/uploads/report.csv", content: "month,total", truncated: false };
  state.fileLoading = false;
  state.fileError = null;
  state.read = [];
  state.flat = null;
  state.flatLoading = false;
  state.flatError = null;
  state.flatAsked = [];
  state.downloaded = [];
  state.downloadError = null;
});

/**
 * The page with every file as a tile, which is how a search lists its matches:
 * every path starts with a slash, so searching for one matches them all. What a
 * tile shows is what these tests are about; the groups have their own file.
 */
function renderAsTiles(): void {
  render(<WorkspaceBrowser />);
  fireEvent.change(screen.getByRole("textbox", { name: "Search files" }), {
    target: { value: "/" },
  });
}

describe("WorkspaceBrowser", () => {
  beforeEach(() => {
    state.flat = {
      items: [
        {
          path: "/report.csv",
          size: 2048,
          is_dir: false,
          modified_at: null,
          preview: null,
          thumbnail: null,
          workspace_id: "w-1",
          agent_id: "a-1",
          agent_name: "Analyst",
          agent_slug: "analyst",
          agent_has_avatar: false,
          access_label: "Everybody who talks to this agent",
          from_upload: false,
        },
      ],
      total: 1,
      workspaces_read: 1,
      unreadable: 0,
      truncated: false,
    };
  });

  it("opens on every file, with no table of workspaces to switch to", () => {
    // "Where is that CSV" is the question people arrive with; which workspaces
    // exist is an operator's question, and each file still opens its folder.
    render(<WorkspaceBrowser />);

    expect(state.flatAsked.at(-1)).toBe(true);
    expect(screen.queryByRole("button", { name: "By workspace" })).toBeNull();
  });

  it("names the workspace each file came from, and links to it", async () => {
    // `/report.csv` exists in several workspaces, so a path on its own is
    // ambiguous - and who can see it is the point of the line beneath it.
    renderAsTiles();

    expect(screen.getByRole("link", { name: "Analyst" })).toHaveAttribute("href", "/documents/w-1");
    // Who else can see it is the workspace's sentence, on the agent's name.
    expect(screen.getByRole("link", { name: "Analyst" })).toHaveAttribute(
      "title",
      "Everybody who talks to this agent",
    );
  });

  it("opens a file into the viewer, because the next question is what is in it", async () => {
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("button", { name: "Open report.csv" }));

    expect(await screen.findByRole("dialog")).toBeVisible();
    expect(state.read).toContain("/report.csv");
  });

  it("closes the viewer again", async () => {
    // The flat grid owns the open state, so the way out is its callback.
    render(<WorkspaceBrowser />);
    await userEvent.click(screen.getByRole("button", { name: "Open report.csv" }));
    await screen.findByRole("dialog");

    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("reads a file's size in the units a person uses, and its suffix as a badge", async () => {
    // The card is the same one the chat panel and composer draw (#136), so its
    // meta line is `TXT · 12 B` - and a file with no measured size keeps the
    // suffix badge rather than showing a dash.
    state.flat = {
      ...state.flat!,
      items: [
        { ...state.flat!.items[0]!, path: "/small.txt", size: 12 },
        { ...state.flat!.items[0]!, path: "/unknown.bin", size: null },
      ],
    };
    render(<WorkspaceBrowser />);

    expect(screen.getByText(/TXT · 12 B/)).toBeVisible();
    expect(screen.getByText(/unknown\.bin/)).toBeVisible();
    expect(screen.getByText(/^BIN$/)).toBeVisible();
  });

  it("names an attachment as it was given, and dates a file it can", async () => {
    // `uploads/0d7d5756-` is the platform's filing; the person called it
    // `handbook.md`, and the full path stays on the name as its tooltip.
    state.flat = {
      ...state.flat!,
      items: [
        {
          ...state.flat!.items[0]!,
          path: "/uploads/0d7d5756-handbook.md",
          from_upload: true,
          preview: "# Handbook",
          modified_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
        },
        { ...state.flat!.items[0]!, path: "/notes.txt", preview: "plain words" },
      ],
    };
    renderAsTiles();

    expect(screen.getByText("handbook.md")).toHaveAttribute(
      "title",
      "/uploads/0d7d5756-handbook.md",
    );
    expect(screen.getByText(/MD · .* · 2h ago/)).toBeVisible();
    expect(screen.getByText("plain words")).toBeInTheDocument();
  });

  it("previews the newest files above the groups once there is more than a screen", async () => {
    const base = state.flat!.items[0]!;
    state.flat = {
      ...state.flat!,
      items: Array.from({ length: 6 }, (_, index) => ({
        ...base,
        path: `/file-${index}.md`,
        modified_at: new Date(Date.now() - index * 60_000).toISOString(),
      })),
      total: 6,
    };
    render(<WorkspaceBrowser />);

    const recent = screen.getByRole("region", { name: "Recent" });
    expect(within(recent).getAllByRole("listitem")).toHaveLength(4);
    await userEvent.click(within(recent).getByRole("button", { name: "Download file-0.md" }));
    expect(state.downloaded).toEqual([["w-1", "/file-0.md"]]);
    await userEvent.click(within(recent).getByRole("button", { name: "Open file-0.md" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("lists what a search found flat, each still opening and downloading", async () => {
    render(<WorkspaceBrowser />);

    await userEvent.type(screen.getByRole("textbox", { name: "Search files" }), "report");
    expect(screen.queryByRole("region", { name: "Analyst" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Download report.csv" }));
    await userEvent.click(screen.getByRole("button", { name: "Open report.csv" }));

    expect(state.downloaded).toEqual([["w-1", "/report.csv"]]);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("offers a download for every file, without opening it first", async () => {
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("button", { name: "Download report.csv" }));

    expect(state.downloaded).toEqual([["w-1", "/report.csv"]]);
  });

  it("says when the answer is partial rather than letting it read as complete", async () => {
    state.flat = { ...state.flat!, truncated: true, workspaces_read: 25, unreadable: 2 };
    render(<WorkspaceBrowser />);

    expect(screen.getByText(/Read 25 workspaces/)).toBeVisible();
    expect(screen.getByText(/2 could not be read/)).toBeVisible();
  });

  it("finds a file by path, by agent and by extension", async () => {
    state.flat = {
      ...state.flat!,
      items: [
        state.flat!.items[0]!,
        {
          ...state.flat!.items[0]!,
          path: "/notes.md",
          workspace_id: "w-2",
          agent_name: "Writer",
        },
      ],
    };
    render(<WorkspaceBrowser />);
    const search = screen.getByRole("textbox", { name: "Search files" });

    await userEvent.type(search, "notes");
    expect(screen.queryByText(/report\.csv/)).toBeNull();
    expect(screen.getByText(/notes\.md/)).toBeVisible();

    await userEvent.clear(search);
    await userEvent.type(search, "Analyst");
    expect(screen.getByText(/report\.csv/)).toBeVisible();
    expect(screen.queryByText(/notes\.md/)).toBeNull();

    await userEvent.clear(search);
    await userEvent.type(search, ".csv");
    expect(screen.getByText(/report\.csv/)).toBeVisible();
    expect(screen.queryByText(/notes\.md/)).toBeNull();
  });

  it("says no file matched rather than showing an empty grid", async () => {
    render(<WorkspaceBrowser />);

    await userEvent.type(screen.getByRole("textbox", { name: "Search files" }), "nowhere");

    expect(screen.getByText(/No file matches that search/)).toBeVisible();
  });

  it("says no file matched the origin filter rather than leaving the groups blank", async () => {
    // Every file here is the agent's: asking for the attached ones leaves none,
    // and grouping an empty list drew nothing at all.
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("combobox", { name: "Who put it there" }));
    await userEvent.click(screen.getByRole("option", { name: "Attached" }));

    expect(screen.getByText(/No file matches that search/)).toBeVisible();
  });

  it("keeps the truncation warning while a filter is applied, and says the search was a sample", async () => {
    // A client-side filter over a truncated listing searched a sample - "1
    // result" with no caveat would claim the search was exhaustive.
    state.flat = { ...state.flat!, truncated: true, workspaces_read: 25 };
    render(<WorkspaceBrowser />);

    await userEvent.type(screen.getByRole("textbox", { name: "Search files" }), "report");

    expect(screen.getByText(/Read 25 workspaces/)).toBeVisible();
    expect(screen.getByText(/searched only the workspaces that were read/)).toBeVisible();
  });

  it("sorts by what a person is hunting: newest first, biggest first", async () => {
    state.flat = {
      ...state.flat!,
      items: [
        {
          ...state.flat!.items[0]!,
          path: "/old.csv",
          size: 10,
          modified_at: "2026-08-01T00:00:00Z",
        },
        {
          ...state.flat!.items[0]!,
          path: "/new.csv",
          size: 5,
          modified_at: "2026-08-16T00:00:00Z",
        },
      ],
    };
    render(<WorkspaceBrowser />);

    // Alphabetical by default, so the order is deterministic before anybody sorts.
    const paths = () => screen.getAllByText(/\.csv/).map((node) => node.textContent?.split(" ")[0]);
    expect(paths()).toEqual(["new.csv", "old.csv"]);

    await userEvent.click(screen.getByRole("combobox", { name: "Sort files" }));
    await userEvent.click(screen.getByRole("option", { name: "By size" }));
    expect(paths()).toEqual(["old.csv", "new.csv"]);

    await userEvent.click(screen.getByRole("combobox", { name: "Sort files" }));
    await userEvent.click(screen.getByRole("option", { name: "By modified" }));
    expect(paths()).toEqual(["new.csv", "old.csv"]);
  });

  it("groups by agent, and orders one agent's own files by path", async () => {
    // "Who is holding a copy of that CSV" is the question this view exists for,
    // so grouping by holder is the sort that answers it - and within a holder
    // the paths have to be stable, or the grid reshuffles between renders.
    state.flat = {
      ...state.flat!,
      items: [
        { ...state.flat!.items[0]!, path: "/zeta.csv", agent_name: "Analyst" },
        { ...state.flat!.items[0]!, path: "/mid.csv", agent_name: "Writer" },
        { ...state.flat!.items[0]!, path: "/alpha.csv", agent_name: "Analyst" },
      ],
    };
    render(<WorkspaceBrowser />);
    const paths = () => screen.getAllByText(/\.csv/).map((node) => node.textContent?.split(" ")[0]);

    await userEvent.click(screen.getByRole("combobox", { name: "Sort files" }));
    await userEvent.click(screen.getByRole("option", { name: "By agent" }));

    expect(paths()).toEqual(["alpha.csv", "zeta.csv", "mid.csv"]);
  });

  it("shows a stored file's first lines on its tile", async () => {
    state.flat = {
      ...state.flat!,
      items: [{ ...state.flat!.items[0]!, path: "/report.md", preview: "# Findings\nline two" }],
    };
    renderAsTiles();

    // Markdown reads as the page it is - the heading drawn as a heading, not
    // its hash - and the line under it stays a line.
    expect(screen.getByText("Findings")).toBeVisible();
    expect(screen.getByText("line two")).toBeVisible();
  });

  it("draws a stored image on its tile rather than a glyph", async () => {
    state.flat = {
      ...state.flat!,
      items: [
        {
          ...state.flat!.items[0]!,
          path: "/chart.png",
          thumbnail: "data:image/webp;base64,UklGRg==",
        },
      ],
    };
    renderAsTiles();

    // `hidden`: the tile's peek is decorative and out of the accessibility tree.
    expect(screen.getByRole("img", { name: "chart.png", hidden: true })).toBeVisible();
  });

  it("draws an image with no thumbnail as its mark, not a broken picture", async () => {
    state.flat = {
      ...state.flat!,
      items: [{ ...state.flat!.items[0]!, path: "/photo.png", thumbnail: null }],
    };
    render(<WorkspaceBrowser />);

    expect(screen.queryByRole("img", { name: "photo.png" })).toBeNull();
  });

  it("says nothing is held rather than showing an empty list", async () => {
    state.flat = { items: [], total: 0, workspaces_read: 0, unreadable: 0, truncated: false };
    render(<WorkspaceBrowser />);

    expect(screen.getByText(/No agent is holding a file yet/)).toBeVisible();
    // And where files come from, with the way there (#2075).
    expect(screen.getByText(/Sandbox capability keeps the files/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Open your agents" }));
  });

  it("reports a failure instead of an empty list", async () => {
    state.flatError = "Those files could not be read";
    render(<WorkspaceBrowser />);

    expect(screen.getByText("Those files could not be read")).toBeVisible();
  });

  it("waits without claiming the list is empty", async () => {
    state.flat = null;
    state.flatLoading = true;
    render(<WorkspaceBrowser />);

    expect(screen.queryByText(/No agent is holding/)).toBeNull();
  });

  it("shows nothing at all before an answer arrives", async () => {
    state.flat = null;
    render(<WorkspaceBrowser />);

    expect(screen.queryByText(/No agent is holding/)).toBeNull();
  });
});

describe("who put a file in the workspace", () => {
  const attached = {
    path: "/uploads/8b1e-book.pdf",
    size: 1024,
    is_dir: false as const,
    modified_at: null,
    preview: null,
    thumbnail: null,
    workspace_id: "w-1",
    agent_id: "a-1",
    agent_name: "Analyst",
    agent_slug: "analyst",
    agent_has_avatar: false,
    access_label: "Whoever is in that conversation",
    from_upload: true,
  };

  beforeEach(() => {
    state.flat = {
      items: [attached, { ...attached, path: "/summary.md", from_upload: false }],
      total: 2,
      workspaces_read: 1,
      unreadable: 0,
      truncated: false,
    };
  });

  it("says of each file whether it was attached or written", () => {
    // A PDF somebody gave the agent and a PDF the agent produced are read for
    // different reasons, and the path is not always the answer.
    renderAsTiles();

    expect(screen.getByText("Attached")).toBeVisible();
    expect(screen.getByText("By the agent")).toBeVisible();
  });

  it("filters to one or the other", async () => {
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("combobox", { name: "Who put it there" }));
    await userEvent.click(screen.getByRole("option", { name: "Attached" }));

    expect(screen.getByText("8b1e-book.pdf")).toBeVisible();
    expect(screen.queryByText("summary.md")).toBeNull();
  });

  it("shows both when nobody narrowed it", () => {
    render(<WorkspaceBrowser />);

    expect(screen.getByText("8b1e-book.pdf")).toBeVisible();
    expect(screen.getByText("summary.md")).toBeVisible();
  });
});

describe("compareFlat", () => {
  it("orders by name, size, change and agent as the sort says", () => {
    const base = { size: 1, modified_at: null, agent_name: "B" } as unknown as FlatFile;
    const a = { ...base, path: "/a.md", size: 1, agent_name: "B" } as FlatFile;
    const b = { ...base, path: "/b.md", size: 9, agent_name: "A" } as FlatFile;
    expect(compareFlat("name", a, b)).toBeLessThan(0);
    expect(compareFlat("size", a, b)).toBeGreaterThan(0);
    expect(compareFlat("agent", a, b)).toBeGreaterThan(0);
    expect(compareFlat("modified", a, b)).toBe(0);
  });
});
