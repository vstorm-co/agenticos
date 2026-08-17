import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceBrowser } from "./workspace-browser";
import type {
  FlatFileList,
  WorkspaceFileContent,
  WorkspaceFiles,
  WorkspaceSummary,
} from "@/lib/sandbox-workspaces-api";

const state = vi.hoisted(() => ({
  workspaces: [] as WorkspaceSummary[],
  listLoading: false,
  listError: null as string | null,
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
  useSandboxWorkspaces: () => ({
    workspaces: state.workspaces,
    isLoading: state.listLoading,
    error: state.listError,
  }),
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

function workspace(overrides: Partial<WorkspaceSummary> = {}): WorkspaceSummary {
  return {
    id: "w-1",
    agent_id: "a-1",
    agent_name: "Analyst",
    agent_has_avatar: false,
    conversation_id: "c-1",
    conversation_is_mine: false,
    conversation_title: "Refund policy",
    conversations: 1,
    scope: "conversation",
    backend: "state",
    owner_label: "This conversation",
    access_label: "Whoever is in that conversation",
    bytes_total: 1_048_576,
    version: 3,
    last_used_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

function files(overrides: Partial<WorkspaceFiles> = {}): WorkspaceFiles {
  return {
    unreadable_reason: null,
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
  state.workspaces = [workspace()];
  state.listLoading = false;
  state.listError = null;
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

describe("WorkspaceBrowser", () => {
  it("names the agent, the chat, and who can see the files", () => {
    // `access_label` is a column, not decoration: under `agent` scope one
    // workspace is shared by everybody who talks to that agent, and a table of
    // paths with no statement of who can see them is the wrong thing to hand
    // somebody auditing this.
    render(<WorkspaceBrowser />);

    expect(screen.getByText("Analyst")).toBeVisible();
    expect(screen.getByText("Refund policy")).toBeVisible();
    expect(screen.getByText("Whoever is in that conversation")).toBeVisible();
  });

  it("counts the chats behind a workspace no single conversation owns", () => {
    // The difference between "my files" and "everybody's", and there is no title
    // to show for one.
    state.workspaces = [
      workspace({ conversation_id: null, conversation_title: null, conversations: 12 }),
    ];

    render(<WorkspaceBrowser />);

    expect(screen.getByText("12 conversations")).toBeVisible();
  });

  it("says nothing about chats for a workspace that ends with its run", () => {
    state.workspaces = [
      workspace({ conversation_id: null, conversation_title: null, conversations: 0 }),
    ];

    render(<WorkspaceBrowser />);

    expect(screen.getByText("—")).toBeVisible();
  });

  it("sorts by agent, and puts a container's unmeasured size last either way", async () => {
    state.workspaces = [
      workspace(),
      workspace({ id: "w-2", backend: "service", agent_name: "Builder", bytes_total: 0 }),
    ];
    render(<WorkspaceBrowser />);
    // The avatar's initials are decoration inside the same cell, so the name
    // is what is left once the aria-hidden part is dropped.
    const firstAgent = () => {
      const cell = screen.getAllByRole("rowgroup")[1]!.querySelector("tr > td")!;
      cell.querySelector('[aria-hidden="true"]')?.remove();
      return cell.textContent;
    };

    await userEvent.click(screen.getByRole("button", { name: "Agent" }));
    expect(firstAgent()).toBe("Builder");

    // Descending by size: the stored workspace has a number, the container
    // has none - and an absence is not a small number, so it sorts last.
    await userEvent.click(screen.getByRole("button", { name: "Size" }));
    expect(firstAgent()).toBe("Analyst");
  });

  it("links the reader's own conversation to its chat", () => {
    state.workspaces = [workspace({ conversation_is_mine: true })];
    render(<WorkspaceBrowser />);

    const link = screen.getByRole("link", { name: "Open the chat these files belong to" });
    expect(link).toHaveAttribute("href", "/chat?id=c-1");
    expect(link).toHaveTextContent("Refund policy");
  });

  it("names an untitled chat rather than drawing a hole", () => {
    state.workspaces = [workspace({ conversation_is_mine: true, conversation_title: null })];
    render(<WorkspaceBrowser />);

    expect(
      screen.getByRole("link", { name: "Open the chat these files belong to" }),
    ).toHaveTextContent("Untitled chat");
  });

  it("offers no chat link on somebody else's conversation", () => {
    // The chat page lists its owner's threads: anybody else's link would land
    // on an empty sidebar dressed as the conversation.
    state.workspaces = [workspace({ conversation_is_mine: false })];
    render(<WorkspaceBrowser />);

    expect(screen.queryByRole("link", { name: "Open the chat these files belong to" })).toBeNull();
    expect(screen.getByText("Refund policy")).toBeVisible();
  });

  it("measures a stored workspace and says a container's files are elsewhere", () => {
    state.workspaces = [
      workspace(),
      workspace({ id: "w-2", backend: "service", agent_name: "Builder" }),
    ];
    render(<WorkspaceBrowser />);

    expect(screen.getByText("1.0 MB")).toBeVisible();
    expect(screen.getByText("on the host")).toBeVisible();
  });

  it("says when a workspace was last touched", () => {
    state.workspaces = [workspace({ last_used_at: null })];
    render(<WorkspaceBrowser />);

    expect(screen.getByText("never")).toBeVisible();
  });

  it("reads a stale date as days ago", () => {
    const when = new Date(Date.now() - 3 * 86_400_000).toISOString();
    state.workspaces = [workspace({ last_used_at: when })];
    render(<WorkspaceBrowser />);

    expect(screen.getByText("3 days ago")).toBeVisible();
  });

  it("reads yesterday as yesterday", () => {
    const when = new Date(Date.now() - 86_400_000 - 1000).toISOString();
    state.workspaces = [workspace({ last_used_at: when })];
    render(<WorkspaceBrowser />);

    expect(screen.getByText("yesterday")).toBeVisible();
  });

  it("reads a workspace with no recorded size as unmeasured", () => {
    // A container's `bytes_total` is the JSONB document's, which is zero for it -
    // so the column says where its files actually are instead of claiming a size.
    state.workspaces = [workspace({ backend: "service" })];
    render(<WorkspaceBrowser />);

    expect(screen.getByText("on the host")).toBeVisible();
  });

  it("says an organization is keeping nothing rather than showing an empty table", () => {
    state.workspaces = [];
    render(<WorkspaceBrowser />);

    expect(screen.getByText(/No agent is keeping files yet/)).toBeVisible();
  });

  it("says why the list is empty when the request failed", () => {
    // An empty table and a failure are otherwise the same pixels.
    state.workspaces = [];
    state.listError = "403 Forbidden";
    render(<WorkspaceBrowser />);

    expect(screen.getByText("403 Forbidden")).toBeVisible();
  });

  it("claims neither emptiness nor failure while the list loads", () => {
    state.workspaces = [];
    state.listLoading = true;
    render(<WorkspaceBrowser />);

    expect(screen.queryByText(/No agent is keeping files yet/)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("opens a workspace as its own page rather than a panel under the table", () => {
    // A workspace with a `skills/` directory is a tree, and a URL is what makes
    // "look at this file" something one person can send another.
    render(<WorkspaceBrowser />);

    expect(screen.getByRole("link", { name: "Files of Analyst" })).toHaveAttribute(
      "href",
      "/workspaces/w-1",
    );
  });

  describe("the flat view", () => {
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
            agent_name: "Analyst",
            access_label: "Everybody who talks to this agent",
          },
        ],
        total: 1,
        workspaces_read: 1,
        unreadable: 0,
        truncated: false,
      };
    });

    it("is not asked for until somebody switches to it", async () => {
      // It reads every workspace in turn - a round trip per container-backed one -
      // so it is not what the page pays for on load.
      render(<WorkspaceBrowser />);
      // Not even asked with `enabled: false` - the component that reads it is not
      // mounted until the view is on.
      expect(state.flatAsked).toEqual([]);

      await userEvent.click(screen.getByRole("button", { name: "All files" }));

      expect(state.flatAsked.at(-1)).toBe(true);
    });

    it("names the workspace each file came from, and links to it", async () => {
      // `/report.csv` exists in several workspaces, so a path on its own is
      // ambiguous - and who can see it is the point of the line beneath it.
      render(<WorkspaceBrowser />);

      await userEvent.click(screen.getByRole("button", { name: "All files" }));

      expect(screen.getByRole("link", { name: "Analyst" })).toHaveAttribute(
        "href",
        "/workspaces/w-1",
      );
      expect(screen.getByText(/Everybody who talks to this agent/)).toBeVisible();
    });

    it("opens a file into the viewer, because the next question is what is in it", async () => {
      render(<WorkspaceBrowser />);
      await userEvent.click(screen.getByRole("button", { name: "All files" }));

      await userEvent.click(screen.getByRole("button", { name: /report\.csv CSV/ }));

      expect(await screen.findByRole("dialog")).toBeVisible();
      expect(state.read).toContain("/report.csv");
    });

    it("closes the viewer again", async () => {
      // The flat grid owns the open state, so the way out is its callback.
      render(<WorkspaceBrowser />);
      await userEvent.click(screen.getByRole("button", { name: "All files" }));
      await userEvent.click(screen.getByRole("button", { name: /report\.csv CSV/ }));
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

      await userEvent.click(screen.getByRole("button", { name: "All files" }));

      expect(screen.getByText(/TXT · 12 B/)).toBeVisible();
      expect(screen.getByText(/unknown\.bin/)).toBeVisible();
      expect(screen.getByText(/^BIN$/)).toBeVisible();
    });

    it("offers a download for every file, without opening it first", async () => {
      render(<WorkspaceBrowser />);

      await userEvent.click(screen.getByRole("button", { name: "All files" }));
      await userEvent.click(screen.getByRole("button", { name: "Download /report.csv" }));

      expect(state.downloaded).toEqual([["w-1", "/report.csv"]]);
    });

    it("says when the answer is partial rather than letting it read as complete", async () => {
      state.flat = { ...state.flat!, truncated: true, workspaces_read: 25, unreadable: 2 };
      render(<WorkspaceBrowser />);

      await userEvent.click(screen.getByRole("button", { name: "All files" }));

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
      await userEvent.click(screen.getByRole("button", { name: "All files" }));
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
      await userEvent.click(screen.getByRole("button", { name: "All files" }));

      await userEvent.type(screen.getByRole("textbox", { name: "Search files" }), "nowhere");

      expect(screen.getByText(/No file matches that search/)).toBeVisible();
    });

    it("keeps the truncation warning while a filter is applied, and says the search was a sample", async () => {
      // A client-side filter over a truncated listing searched a sample - "1
      // result" with no caveat would claim the search was exhaustive.
      state.flat = { ...state.flat!, truncated: true, workspaces_read: 25 };
      render(<WorkspaceBrowser />);
      await userEvent.click(screen.getByRole("button", { name: "All files" }));

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
      await userEvent.click(screen.getByRole("button", { name: "All files" }));

      // Alphabetical by default, so the order is deterministic before anybody sorts.
      const paths = () =>
        screen.getAllByText(/\.csv/).map((node) => node.textContent?.split(" ")[0]);
      expect(paths()).toEqual(["/new.csv", "/old.csv"]);

      await userEvent.click(screen.getByRole("combobox", { name: "Sort files" }));
      await userEvent.click(screen.getByRole("option", { name: "By size" }));
      expect(paths()).toEqual(["/old.csv", "/new.csv"]);

      await userEvent.click(screen.getByRole("combobox", { name: "Sort files" }));
      await userEvent.click(screen.getByRole("option", { name: "By modified" }));
      expect(paths()).toEqual(["/new.csv", "/old.csv"]);
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
      await userEvent.click(screen.getByRole("button", { name: "All files" }));
      const paths = () =>
        screen.getAllByText(/\.csv/).map((node) => node.textContent?.split(" ")[0]);

      await userEvent.click(screen.getByRole("combobox", { name: "Sort files" }));
      await userEvent.click(screen.getByRole("option", { name: "By agent" }));

      expect(paths()).toEqual(["/alpha.csv", "/zeta.csv", "/mid.csv"]);
    });

    it("shows a stored file's first lines on its tile", async () => {
      state.flat = {
        ...state.flat!,
        items: [{ ...state.flat!.items[0]!, path: "/report.md", preview: "# Findings\nline two" }],
      };
      render(<WorkspaceBrowser />);

      await userEvent.click(screen.getByRole("button", { name: "All files" }));

      expect(screen.getByText(/# Findings/)).toBeVisible();
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
      render(<WorkspaceBrowser />);

      await userEvent.click(screen.getByRole("button", { name: "All files" }));

      expect(screen.getByRole("img", { name: "/chart.png" })).toBeVisible();
    });

    it("draws an image with no thumbnail as its mark, not a broken picture", async () => {
      state.flat = {
        ...state.flat!,
        items: [{ ...state.flat!.items[0]!, path: "/photo.png", thumbnail: null }],
      };
      render(<WorkspaceBrowser />);

      await userEvent.click(screen.getByRole("button", { name: "All files" }));

      expect(screen.queryByRole("img", { name: "/photo.png" })).toBeNull();
    });

    it("says nothing is held rather than showing an empty list", async () => {
      state.flat = { items: [], total: 0, workspaces_read: 0, unreadable: 0, truncated: false };
      render(<WorkspaceBrowser />);

      await userEvent.click(screen.getByRole("button", { name: "All files" }));

      expect(screen.getByText(/No agent is holding a file yet/)).toBeVisible();
    });

    it("reports a failure instead of an empty list", async () => {
      state.flatError = "Those files could not be read";
      render(<WorkspaceBrowser />);

      await userEvent.click(screen.getByRole("button", { name: "All files" }));

      expect(screen.getByText("Those files could not be read")).toBeVisible();
    });

    it("waits without claiming the list is empty", async () => {
      state.flat = null;
      state.flatLoading = true;
      render(<WorkspaceBrowser />);

      await userEvent.click(screen.getByRole("button", { name: "All files" }));

      expect(screen.queryByText(/No agent is holding/)).toBeNull();
    });

    it("shows nothing at all before an answer arrives", async () => {
      state.flat = null;
      render(<WorkspaceBrowser />);

      await userEvent.click(screen.getByRole("button", { name: "All files" }));

      expect(screen.queryByText(/No agent is holding/)).toBeNull();
    });

    it("goes back to the workspace table", async () => {
      render(<WorkspaceBrowser />);
      await userEvent.click(screen.getByRole("button", { name: "All files" }));

      await userEvent.click(screen.getByRole("button", { name: "By workspace" }));

      expect(screen.getByText("Analyst")).toBeVisible();
      expect(screen.queryByText("/report.csv")).toBeNull();
    });
  });
});
