import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceBrowser } from "./workspace-browser";
import type {
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
}));

vi.mock("@/hooks", () => ({
  useSandboxWorkspaces: () => ({
    workspaces: state.workspaces,
    isLoading: state.listLoading,
    error: state.listError,
  }),
  useWorkspaceFiles: (id: string | null) => {
    state.opened.push(id);
    return { files: state.files, isLoading: state.filesLoading, error: state.filesError };
  },
  useWorkspaceFile: (_id: string | null, path: string | null) => {
    state.read.push(path);
    return { file: state.file, isLoading: state.fileLoading, error: state.fileError };
  },
}));

function workspace(overrides: Partial<WorkspaceSummary> = {}): WorkspaceSummary {
  return {
    id: "w-1",
    agent_id: "a-1",
    agent_name: "Analyst",
    conversation_id: "c-1",
    scope: "conversation",
    backend: "state",
    owner_label: "This conversation",
    bytes_total: 1_048_576,
    version: 3,
    last_used_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

function files(overrides: Partial<WorkspaceFiles> = {}): WorkspaceFiles {
  return {
    scope: "conversation",
    backend: "state",
    owner_label: "This conversation",
    items: [{ path: "/uploads/report.csv", size: 128, is_dir: false }],
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
});

describe("WorkspaceBrowser", () => {
  it("names the agent and who shares the workspace", () => {
    // `owner_label` is a column, not decoration: under `agent` scope one
    // workspace is shared by everybody who talks to that agent, and a table of
    // paths with no statement of who can see them is the wrong thing to hand
    // somebody auditing this.
    render(<WorkspaceBrowser />);

    expect(screen.getByText("Analyst")).toBeVisible();
    expect(screen.getByText("This conversation")).toBeVisible();
  });

  it("measures a stored workspace and says a container's files are elsewhere", () => {
    state.workspaces = [
      workspace(),
      workspace({ id: "w-2", backend: "service", agent_name: "Builder" }),
    ];
    render(<WorkspaceBrowser />);

    expect(screen.getByText("1.0 MiB")).toBeVisible();
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

  it("draws a placeholder while the list loads", () => {
    state.workspaces = [];
    state.listLoading = true;
    render(<WorkspaceBrowser />);

    expect(document.querySelector(".h-10")).not.toBeNull();
  });

  it("reads no files until a workspace is opened", async () => {
    // Which is why the listing carries none: this is a request per workspace, and
    // for a container-backed one it reads the host volume.
    render(<WorkspaceBrowser />);

    expect(state.opened).toEqual([]);

    await userEvent.click(screen.getByRole("button", { name: "Files of Analyst" }));

    expect(state.opened.at(-1)).toBe("w-1");
    expect(screen.getByText("/uploads/report.csv")).toBeVisible();
  });

  it("closes again on a second press", async () => {
    render(<WorkspaceBrowser />);
    const toggle = screen.getByRole("button", { name: "Files of Analyst" });

    await userEvent.click(toggle);
    await userEvent.click(toggle);

    expect(screen.queryByText("/uploads/report.csv")).toBeNull();
  });

  it("says an opened workspace is empty rather than showing nothing", async () => {
    state.files = files({ items: [], total: 0 });
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("button", { name: "Files of Analyst" }));

    expect(screen.getByText(/This workspace is empty/)).toBeVisible();
  });

  it("reports a workspace that could not be read", async () => {
    state.files = null;
    state.filesError = "The sandbox service did not answer";
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("button", { name: "Files of Analyst" }));

    expect(screen.getByText("The sandbox service did not answer")).toBeVisible();
  });

  it("draws a placeholder while a workspace opens", async () => {
    state.files = null;
    state.filesLoading = true;
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("button", { name: "Files of Analyst" }));

    expect(document.querySelector(".h-16")).not.toBeNull();
  });

  it("reads a file only when somebody asks for it", async () => {
    render(<WorkspaceBrowser />);
    await userEvent.click(screen.getByRole("button", { name: "Files of Analyst" }));

    expect(state.read).toEqual([]);

    await userEvent.click(screen.getByRole("button", { name: "Read /uploads/report.csv" }));

    expect(state.read.at(-1)).toBe("/uploads/report.csv");
    expect(screen.getByText("month,total")).toBeVisible();
  });

  it("closes a file on a second press", async () => {
    render(<WorkspaceBrowser />);
    await userEvent.click(screen.getByRole("button", { name: "Files of Analyst" }));
    const toggle = screen.getByRole("button", { name: "Read /uploads/report.csv" });

    await userEvent.click(toggle);
    await userEvent.click(toggle);

    expect(screen.queryByText("month,total")).toBeNull();
  });

  it("offers no Read for a directory entry", async () => {
    state.files = files({ items: [{ path: "/uploads", size: null, is_dir: true }] });
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("button", { name: "Files of Analyst" }));

    expect(screen.queryByRole("button", { name: /^Read/ })).toBeNull();
    expect(screen.getByText("—")).toBeVisible();
  });

  it("reports a file that could not be read", async () => {
    state.file = null;
    state.fileError = "That file could not be read";
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("button", { name: "Files of Analyst" }));
    await userEvent.click(screen.getByRole("button", { name: "Read /uploads/report.csv" }));

    expect(screen.getByText("That file could not be read")).toBeVisible();
  });

  it("draws a placeholder while a file loads", async () => {
    state.file = null;
    state.fileLoading = true;
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("button", { name: "Files of Analyst" }));
    await userEvent.click(screen.getByRole("button", { name: "Read /uploads/report.csv" }));

    expect(document.querySelector(".h-24")).not.toBeNull();
  });

  it("renders nothing for a file that answered with neither content nor an error", async () => {
    state.file = null;
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("button", { name: "Files of Analyst" }));
    await userEvent.click(screen.getByRole("button", { name: "Read /uploads/report.csv" }));

    expect(screen.queryByText("month,total")).toBeNull();
  });

  it("reads a file's size in kibibytes", async () => {
    state.files = files({ items: [{ path: "/notes.md", size: 4096, is_dir: false }] });
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("button", { name: "Files of Analyst" }));

    expect(screen.getByText("4 KiB")).toBeVisible();
  });

  it("reads a small file's size in bytes", async () => {
    state.files = files({ items: [{ path: "/a.txt", size: 12, is_dir: false }] });
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("button", { name: "Files of Analyst" }));

    expect(screen.getByText("12 B")).toBeVisible();
  });

  it("reads a large file's size in mebibytes", async () => {
    state.files = files({ items: [{ path: "/big.csv", size: 2_097_152, is_dir: false }] });
    render(<WorkspaceBrowser />);

    await userEvent.click(screen.getByRole("button", { name: "Files of Analyst" }));

    expect(screen.getByText("2.0 MiB")).toBeVisible();
  });
});
