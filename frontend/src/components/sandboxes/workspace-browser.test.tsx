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
  measureAsked: [] as boolean[],
  unreadable: 0,
  truncated: false,
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
  useSandboxWorkspaces: (measure: boolean) => {
    state.measureAsked.push(measure);
    return {
      workspaces: state.workspaces,
      measured: state.workspaces.length,
      unreadable: state.unreadable,
      truncated: state.truncated,
      isLoading: state.listLoading,
      error: state.listError,
    };
  },
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
    file_count: 4,
    measured_bytes: 1_048_576,
    version: 3,
    last_used_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

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
  state.workspaces = [workspace()];
  state.measureAsked = [];
  state.unreadable = 0;
  state.truncated = false;
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

/**
 * The table, which is no longer the landing view.
 *
 * `All files` is what the page opens on - "where is that CSV" and "what did the
 * agent write" are the questions somebody arrives with. Every test about the table
 * therefore switches to it first, in one place rather than twenty.
 */
async function showTable() {
  render(<WorkspaceBrowser />);
  await userEvent.click(screen.getByRole("button", { name: "By workspace" }));
}

describe("WorkspaceBrowser", () => {
  it("names the agent, the chat, and who can see the files", async () => {
    // `access_label` is a column, not decoration: under `agent` scope one
    // workspace is shared by everybody who talks to that agent, and a table of
    // paths with no statement of who can see them is the wrong thing to hand
    // somebody auditing this.
    await showTable();

    expect(screen.getByText("Analyst")).toBeVisible();
    expect(screen.getByText("Refund policy")).toBeVisible();
    expect(screen.getByText("Whoever is in that conversation")).toBeVisible();
  });

  it("names the owner beside who else can see the files", async () => {
    // Two different facts, and the table used to carry only the second:
    // `access_label` describes the *scope* - "everybody who talks to this
    // agent" - and never names the person. On an agent-scoped workspace shared
    // by six people that is the question an operator has (#137).
    state.workspaces = [
      workspace({
        owner_label: "nina@example.com",
        access_label: "Everybody who talks to Analyst",
      }),
    ];

    await showTable();

    expect(screen.getByRole("columnheader", { name: "Owner" })).toBeVisible();
    expect(screen.getByText("nina@example.com")).toBeVisible();
    expect(screen.getByText("Everybody who talks to Analyst")).toBeVisible();
  });

  it("sorts by owner, which is how somebody groups a deployment by holder", async () => {
    state.workspaces = [
      workspace({ owner_label: "zoe@example.com", conversation_title: "Refund policy" }),
      workspace({
        id: "w-2",
        owner_label: "ada@example.com",
        conversation_title: "Webhook wiring",
      }),
    ];
    await showTable();

    const firstRow = () => {
      const cell = screen.getAllByRole("rowgroup")[1]!.querySelector("tr > td")!;
      cell.querySelector('[aria-hidden="true"]')?.remove();
      return cell.textContent;
    };

    // Descending first, like every other column here.
    await userEvent.click(screen.getByRole("button", { name: "Owner" }));
    expect(firstRow()).toContain("Refund policy");

    await userEvent.click(screen.getByRole("button", { name: "Owner" }));
    expect(firstRow()).toContain("Webhook wiring");
  });

  it("draws a platform-sourced owner as words, not a destination", async () => {
    // `owner_ref` is a string and a Slack-sourced workspace's owner is a
    // platform id rather than an account, so a linked cell would be broken on
    // half the rows (#131).
    state.workspaces = [workspace({ owner_label: "slack:U024BE7LH" })];

    await showTable();

    expect(screen.getByText("slack:U024BE7LH")).toBeVisible();
    expect(screen.queryByRole("link", { name: "slack:U024BE7LH" })).toBeNull();
  });

  it("counts the chats behind a workspace no single conversation owns", async () => {
    // The difference between "my files" and "everybody's", and there is no title
    // to show for one.
    state.workspaces = [
      workspace({ conversation_id: null, conversation_title: null, conversations: 12 }),
    ];

    await showTable();

    expect(screen.getByText(/12 conversations/)).toBeVisible();
  });

  it("leads with whose it is for a workspace that ends with its run", async () => {
    // No chat to name it after and no count to give, so the heading is the owner
    // - which under `agent` scope is the whole point of the row.
    state.workspaces = [
      workspace({
        conversation_id: null,
        conversation_title: null,
        conversations: 0,
        owner_label: "Every chat with Analyst",
      }),
    ];

    await showTable();

    expect(screen.getByRole("link", { name: "Every chat with Analyst" })).toBeVisible();
    // Not the access label, which legitimately says "conversation": a count.
    expect(screen.queryByText(/\d+ conversations/)).toBeNull();
  });

  it("sorts by what the row leads with, and puts an unmeasured workspace last", async () => {
    state.workspaces = [
      workspace(),
      // Alphabetically last *and* the unmeasured one, so the two orders this
      // asserts cannot agree by accident.
      workspace({
        id: "w-2",
        backend: "service",
        agent_name: "Builder",
        conversation_title: "Webhook wiring",
        bytes_total: 0,
      }),
    ];
    await showTable();
    // The avatar's initials are decoration inside the same cell, so the heading
    // is what is left once the aria-hidden part is dropped.
    const firstRow = () => {
      const cell = screen.getAllByRole("rowgroup")[1]!.querySelector("tr > td")!;
      cell.querySelector('[aria-hidden="true"]')?.remove();
      return cell.textContent;
    };

    await userEvent.click(screen.getByRole("button", { name: "Workspace" }));
    expect(firstRow()).toContain("Webhook wiring");

    // Descending: the stored workspace has a number, the container has none -
    // and an absence is not a small number, so it sorts last.
    await userEvent.click(screen.getByRole("button", { name: "Size" }));
    expect(firstRow()).toContain("Refund policy");
  });

  it("links the reader's own conversation to its chat", async () => {
    state.workspaces = [workspace({ conversation_is_mine: true })];
    await showTable();

    const link = screen.getByRole("link", { name: "Open the chat these files belong to" });
    expect(link).toHaveAttribute("href", "/chat?id=c-1");
    // The title is the row's heading now; this link is the icon beside the agent,
    // so what identifies it is its label rather than its text.
    expect(screen.getByRole("link", { name: "Refund policy" })).toBeVisible();
  });

  it("names an untitled chat rather than drawing a hole", async () => {
    state.workspaces = [workspace({ conversation_is_mine: true, conversation_title: null })];
    await showTable();

    expect(screen.getByRole("link", { name: "Untitled chat" })).toBeVisible();
  });

  it("offers no chat link on somebody else's conversation", async () => {
    // The chat page lists its owner's threads: anybody else's link would land
    // on an empty sidebar dressed as the conversation.
    state.workspaces = [workspace({ conversation_is_mine: false })];
    await showTable();

    expect(screen.queryByRole("link", { name: "Open the chat these files belong to" })).toBeNull();
    expect(screen.getByText("Refund policy")).toBeVisible();
  });

  it("counts the files and weighs them, in two columns", async () => {
    state.workspaces = [
      workspace({ file_count: 4, measured_bytes: 1_048_576 }),
      workspace({
        id: "w-2",
        backend: "service",
        agent_name: "Builder",
        conversation_title: "Webhook wiring",
        file_count: null,
        measured_bytes: null,
      }),
    ];
    await showTable();

    expect(screen.getByText("4")).toBeVisible();
    expect(screen.getByText("1.0 MB")).toBeVisible();
    // Nobody counted the container's: `—` and not `0`, which would be a claim.
    expect(screen.getAllByText("—")).toHaveLength(2);
  });

  it("says when a workspace was last touched", async () => {
    state.workspaces = [workspace({ last_used_at: null })];
    await showTable();

    expect(screen.getByText("never")).toBeVisible();
  });

  it("reads a stale date as days ago", async () => {
    const when = new Date(Date.now() - 3 * 86_400_000).toISOString();
    state.workspaces = [workspace({ last_used_at: when })];
    await showTable();

    expect(screen.getByText("3 days ago")).toBeVisible();
  });

  it("reads yesterday as yesterday", async () => {
    const when = new Date(Date.now() - 86_400_000 - 1000).toISOString();
    state.workspaces = [workspace({ last_used_at: when })];
    await showTable();

    expect(screen.getByText("yesterday")).toBeVisible();
  });

  it("reads a workspace with no recorded size as unmeasured", async () => {
    // `bytes_total` is the stored document's size and zero for a container, so a
    // size column reading it would call every container empty. `measured_bytes` is
    // null until somebody counts, and null prints as an absence.
    state.workspaces = [workspace({ backend: "service", file_count: null, measured_bytes: null })];
    await showTable();

    expect(screen.getAllByText("—")).toHaveLength(2);
  });

  it("says an organization is keeping nothing rather than showing an empty table", async () => {
    state.workspaces = [];
    await showTable();

    expect(screen.getByText(/No agent is keeping files yet/)).toBeVisible();
  });

  it("says why the list is empty when the request failed", async () => {
    // An empty table and a failure are otherwise the same pixels.
    state.workspaces = [];
    state.listError = "403 Forbidden";
    await showTable();

    expect(screen.getByText("403 Forbidden")).toBeVisible();
  });

  it("claims neither emptiness nor failure while the list loads", async () => {
    state.workspaces = [];
    state.listLoading = true;
    await showTable();

    expect(screen.queryByText(/No agent is keeping files yet/)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("opens a workspace as its own page rather than a panel under the table", async () => {
    // A workspace with a `skills/` directory is a tree, and a URL is what makes
    // "look at this file" something one person can send another. What the row
    // leads with is that link - the trailing `Open` button was a seventh column
    // saying what the row already meant (#1039).
    await showTable();

    expect(screen.getByRole("link", { name: "Refund policy" })).toHaveAttribute(
      "href",
      "/workspaces/w-1",
    );
  });

  it("says who can see the files without repeating what holds them", async () => {
    // The `container` badge beside the access label repeated on every row of a
    // deployment that runs one kind of host - a column of one word, twenty times,
    // saying what `Where` says once per row.
    await showTable();

    const cell = screen.getByText("Whoever is in that conversation").closest("td")!;

    expect(cell).not.toHaveTextContent("container");
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
            from_upload: false,
          },
        ],
        total: 1,
        workspaces_read: 1,
        unreadable: 0,
        truncated: false,
      };
    });

    it("is what the page opens on, and the table is the second question", async () => {
      // It reads every workspace in turn - a round trip per container-backed one -
      // and that is the cost of the question people arrive with: "where is that
      // CSV". Which workspaces exist is what an operator asks next.
      render(<WorkspaceBrowser />);

      expect(state.flatAsked.at(-1)).toBe(true);

      await userEvent.click(screen.getByRole("button", { name: "By workspace" }));

      // Unmounted rather than re-asked with `enabled: false`.
      expect(screen.getByRole("button", { name: "By workspace" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
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

describe("what a row is about", () => {
  it("leads with the conversation, because that is what the rows differ by", async () => {
    // An organization runs a handful of agents and a great many conversations, so
    // an agent's name as the heading made twenty rows all called `jarvis`.
    state.workspaces = [
      workspace({ conversation_title: "Refund policy" }),
      workspace({ id: "w-2", conversation_title: "Webhook wiring" }),
    ];

    await showTable();

    expect(screen.getByRole("link", { name: "Refund policy" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Webhook wiring" })).toBeVisible();
    // Twice, once per row, and no longer the thing being read first.
    expect(screen.getAllByText("Analyst")).toHaveLength(2);
  });

  it("counts the workspaces rather than repeating the page's own sentences", async () => {
    // The card's count line carried the two sentences the page header already
    // shows, so the same prose was on screen twice. `counted` is a count.
    await showTable();

    expect(screen.getByText("1 workspace")).toBeVisible();
    expect(screen.queryByText(/A workspace is scratch space/)).toBeNull();
  });
});

describe("counting the files", () => {
  it("sorts by the count, and puts an uncounted workspace last", async () => {
    // An absence is not a small number: a container nobody measured must not sort
    // as though it held nothing.
    state.workspaces = [
      workspace({ file_count: 2, conversation_title: "Two" }),
      workspace({ id: "w-2", file_count: 9, conversation_title: "Nine" }),
      workspace({ id: "w-3", file_count: null, conversation_title: "Unknown" }),
    ];
    await showTable();

    await userEvent.click(screen.getByRole("button", { name: "Files" }));

    const rows = screen.getAllByRole("row").slice(1);

    expect(rows[0]).toHaveTextContent("Nine");
    expect(rows[2]).toHaveTextContent("Unknown");
  });

  it("asks the hosts only when told to", async () => {
    // A round trip per workspace, so the page does not pay for it on open.
    await showTable();

    expect(state.measureAsked.at(-1)).toBe(false);

    await userEvent.click(screen.getByRole("switch", { name: "Count files" }));

    expect(state.measureAsked.at(-1)).toBe(true);
  });

  it("says when a host stayed silent rather than leaving a dash to explain it", async () => {
    // A row reading `—` because its host was down is indistinguishable from a
    // workspace holding nothing.
    state.unreadable = 2;
    await showTable();

    await userEvent.click(screen.getByRole("switch", { name: "Count files" }));

    expect(screen.getByText(/2 hosts did not answer/)).toBeVisible();
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
    agent_name: "Analyst",
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
    render(<WorkspaceBrowser />);

    expect(screen.getByText("Attached")).toBeVisible();
    expect(screen.getByText("By the agent")).toBeVisible();
  });

  it("filters to one or the other", async () => {
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("combobox", { name: "Who put it there" }));
    await userEvent.click(screen.getByRole("option", { name: "Attached" }));

    expect(screen.getByText("/uploads/8b1e-book.pdf")).toBeVisible();
    expect(screen.queryByText("/summary.md")).toBeNull();
  });

  it("shows both when nobody narrowed it", () => {
    render(<WorkspaceBrowser />);

    expect(screen.getByText("/uploads/8b1e-book.pdf")).toBeVisible();
    expect(screen.getByText("/summary.md")).toBeVisible();
  });
});
