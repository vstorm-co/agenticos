import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { FlatFile } from "@/lib/sandbox-workspaces-api";

import { groupByWorkspace, WorkspaceGroups } from "./workspace-groups";

function file(path: string, overrides: Partial<FlatFile> = {}): FlatFile {
  return {
    path,
    size: 10,
    is_dir: false,
    modified_at: "2026-10-17T10:00:00Z",
    preview: null,
    thumbnail: null,
    workspace_id: "w-1",
    agent_id: "a-1",
    agent_name: "Coder",
    agent_slug: "coder",
    agent_has_avatar: false,
    access_label: "Whoever is in that conversation",
    conversation_title: "Build a landing page",
    from_upload: false,
    ...overrides,
  };
}

describe("grouping Documents by the workspace that holds them", () => {
  it("folds each project's folders and keeps its loose files and attachments", () => {
    const [group] = groupByWorkspace([
      file("README.md"),
      file("app/main.py"),
      file("/workspace/app/models.py"),
      file("app/templates/base.html"),
      file("tests/test_app.py"),
      file("/uploads/0d7d5756-brief.pdf", { from_upload: true }),
    ]);

    expect(group!.files.map((entry) => entry.path)).toEqual([
      "README.md",
      "/uploads/0d7d5756-brief.pdf",
    ]);
    expect(group!.folders).toEqual([
      { name: "app", count: 3, sample: ["main.py", "models.py", "base.html"] },
      { name: "tests", count: 1, sample: ["test_app.py"] },
    ]);
    expect(group!.total).toBe(6);
  });

  it("puts the workspace changed most recently first", () => {
    const groups = groupByWorkspace([
      file("old.md", { workspace_id: "w-old", modified_at: "2026-10-01T00:00:00Z" }),
      file("new.md", { workspace_id: "w-new", modified_at: "2026-10-17T00:00:00Z" }),
      file("unknown.md", { workspace_id: "w-undated", modified_at: null }),
    ]);
    expect(groups.map((group) => group.workspaceId)).toEqual(["w-new", "w-old", "w-undated"]);
  });

  it("names the conversation, or the scope where there is none", () => {
    const groups = groupByWorkspace([
      file("a.md"),
      file("b.md", { workspace_id: "w-2", conversation_title: null }),
    ]);
    render(<WorkspaceGroups groups={groups} onOpen={vi.fn()} onDownload={vi.fn()} />);

    expect(screen.getByText(/Build a landing page/)).toBeInTheDocument();
    expect(screen.getByText(/Whoever is in that conversation/)).toBeInTheDocument();
  });

  it("shows a group's first rows, links its chat and its folder for the rest", async () => {
    const onOpen = vi.fn();
    const onDownload = vi.fn();
    const many = Array.from({ length: 10 }, (_, index) => file(`note-${index}.md`));
    render(
      <WorkspaceGroups
        groups={groupByWorkspace([
          file("app/main.py", { conversation_id: "c-1" }),
          file("/uploads/0d7d5756-brief.pdf", { from_upload: true, size: null, modified_at: null }),
          ...many,
        ])}
        onOpen={onOpen}
        onDownload={onDownload}
      />,
    );
    const group = screen.getByRole("region", { name: "Build a landing page" });

    expect(within(group).getByRole("link", { name: "Build a landing page" })).toHaveAttribute(
      "href",
      "/chat?id=c-1",
    );
    expect(within(group).getByText("1 file · main.py")).toBeInTheDocument();
    expect(within(group).getByText("PDF · Attached")).toBeInTheDocument();
    expect(within(group).getByText("4 more in the folder")).toHaveAttribute(
      "href",
      "/documents/w-1",
    );
    await userEvent.click(within(group).getByRole("button", { name: "Open note-0.md" }));
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ path: "note-0.md" }));
    await userEvent.click(within(group).getByRole("button", { name: "Download note-0.md" }));
    expect(onDownload).toHaveBeenCalledWith(expect.objectContaining({ path: "note-0.md" }));
  });

  it("draws a stored image's thumbnail on its row", () => {
    const { container } = render(
      <WorkspaceGroups
        groups={groupByWorkspace([
          file("chart.png", { thumbnail: "data:image/png;base64,AAAA", modified_at: null }),
        ])}
        onOpen={vi.fn()}
        onDownload={vi.fn()}
      />,
    );
    expect(container.querySelector("img")).toHaveAttribute("src", "data:image/png;base64,AAAA");
  });
});
