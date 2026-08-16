import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceFiles } from "./workspace-files";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), raw: vi.fn() },
}));

vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="rendered">{content}</div>
  ),
}));

function draw(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

/** The panel is closed by default; every test about its contents opens it. */
async function openPanel() {
  await userEvent.click(await screen.findByRole("button", { name: /^Show the files/ }));
}

function workspace(overrides: Record<string, unknown> = {}) {
  return {
    scope: "conversation",
    unreadable_reason: null,
    backend: "state",
    owner_label: "This conversation",
    items: [
      { path: "/report.csv", size: 2048, is_dir: false, modified_at: "2026-08-16T11:58:00Z" },
      { path: "/out", size: null, is_dir: true, modified_at: null },
    ],
    total: 2,
    bytes_total: 2048,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue(workspace());
});

/**
 * The panel beside the transcript.
 *
 * Two properties carry it. It is always reachable - a strip holding one icon,
 * because hiding it until a workspace row exists made it unreachable for the whole
 * of a parked turn and for every upload that arrived before the agent did anything.
 * And it says whose files these are, because under `agent` scope one workspace is
 * shared and finding a file you did not create reads as a leak until something on
 * screen explains it.
 *
 * It lists both directions: what the agent wrote, and what people attached. Those
 * are not the same thing - an agent with no workspace can be shown an attachment and
 * cannot open it - so they are separate groups, and an attachment the agent already
 * has a copy of is one file rather than two.
 */
describe("the workspace panel", () => {
  it("lists what the agent is keeping as tiles, with what each file weighs", async () => {
    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();

    // The name, not the path: a 288-pixel column of monospace paths is unreadable,
    // and the whole path is on the tile's title and in the viewer it opens.
    await waitFor(() => expect(screen.getByText("report.csv")).toBeVisible());
    // Type and size on one line, which is what the shared card shows wherever a file
    // is shown without being opened.
    expect(screen.getByText("CSV · 2.0 KB")).toBeVisible();
  });

  it("says whose files these are", async () => {
    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();

    await waitFor(() => expect(screen.getByText(/This conversation/)).toBeVisible());
  });

  it("reports what a stored workspace is holding in total", async () => {
    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();

    await waitFor(() => expect(screen.getByText(/2\.0 KB stored/)).toBeVisible());
  });

  it("is still reachable for an agent that keeps no files, and says so inside", async () => {
    // It used to be absent, on the grounds that a box saying "nothing yet" beside
    // every chat is furniture. But the strip is one icon, and hiding it meant the
    // panel could not be opened at the two moments somebody wants it: a turn that
    // writes a file and then parks for approval has flushed no row, and an upload
    // arrives before the agent has done anything at all. Both looked like an agent
    // with no workspace, and a page reload was the only way back.
    //
    // "No workspace" and "empty workspace" are two answers now, because a wait that
    // will never end is not the same as one that will.
    vi.mocked(apiClient.get).mockResolvedValue(
      workspace({ backend: "none", items: [], total: 0, bytes_total: 0 }),
    );

    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();

    expect(screen.getByText(/keeps no files/)).toBeVisible();
  });

  it("draws the button while the listing is still in flight, and never takes it away", async () => {
    // The old behaviour waited for the answer, to stop the button flickering: it
    // used to appear as the id arrived, vanish when the listing said there was no
    // workspace yet - there is no row until a turn flushes one - and come back when
    // the turn ended.
    //
    // Waiting solved the flicker by making the panel unreachable for the length of
    // the round trip and for the whole of a parked turn. The flicker is solved at
    // the source instead: the button's shape never depends on the listing, only the
    // count does, and a count appears when there is something to count.
    let answer: (value: unknown) => void = () => {};
    vi.mocked(apiClient.get).mockImplementation(() => new Promise((resolve) => (answer = resolve)));

    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);

    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: /^Show the files/ })).toBeVisible();

    answer(workspace());
    expect(await screen.findByRole("button", { name: /Show the files \(1\)/ })).toBeVisible();
  });

  it("is absent before a conversation exists", () => {
    const { container } = draw(
      <WorkspaceFiles conversationId={null} attachments={[]} revision={0} />,
    );

    expect(container).toBeEmptyDOMElement();
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("does not list a directory as a file", async () => {
    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();

    await waitFor(() => expect(screen.getByText("report.csv")).toBeVisible());
    expect(screen.queryByText("out")).toBeNull();
  });

  it("says the workspace is empty when it is, rather than showing nothing", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(workspace({ items: [], total: 0, bytes_total: 0 }));

    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();

    await waitFor(() => expect(screen.getByText(/Nothing yet/)).toBeVisible());
  });

  it("reports a workspace it could not read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("The sandbox service is unreachable"));

    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();

    await waitFor(() =>
      expect(screen.getByText("The sandbox service is unreachable")).toBeVisible(),
    );
  });

  it("re-reads when a turn ends", async () => {
    // The whole reason the panel takes a revision rather than polling: the chat
    // knows when the files could have changed, and a timer is wrong nearly every
    // time it fires.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={client}>
        <WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />
      </QueryClientProvider>,
    );
    await openPanel();
    await waitFor(() => expect(screen.getByText("report.csv")).toBeVisible());
    const before = vi.mocked(apiClient.get).mock.calls.length;

    rerender(
      <QueryClientProvider client={client}>
        <WorkspaceFiles conversationId="c1" attachments={[]} revision={1} />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(vi.mocked(apiClient.get).mock.calls.length).toBeGreaterThan(before));
  });

  it("opens a file into the viewer, and closes it again", async () => {
    // A `<pre>` under the row was the panel showing a report as the first sixty
    // characters of a line. The viewer is shared with the Workspaces screen, so a
    // file means the same thing wherever it was clicked.
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.includes("/file")
        ? { path: "/report.csv", content: "month,total", truncated: false }
        : workspace(),
    );

    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();

    await userEvent.click(await screen.findByRole("button", { name: /report\.csv/ }));
    // A table, which is what the panel could not do: a CSV an agent wrote used to
    // render as a wall of commas here and as bytes-and-a-download for every other kind.
    await waitFor(() => expect(screen.getByRole("columnheader", { name: "month" })).toBeVisible());
    expect(screen.getByRole("dialog")).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("says when the file changed, which only the listing knows (#500)", async () => {
    // The viewer's header read `MD · 3 B` and stopped: `ViewerFile.modifiedAt`
    // existed and the header rendered it, but the workspace listing had no time
    // to give. Now it does, and the panel passes it through.
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.includes("/file")
        ? { path: "/report.csv", content: "month,total", truncated: false }
        : workspace(),
    );

    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();
    await userEvent.click(await screen.findByRole("button", { name: /report\.csv/ }));

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByText(/modified/i)).toBeVisible());
  });

  it("reads a file through its conversation, which is what a shared chat can do", async () => {
    // Not through the workspace's own id: that route is scoped to conversations the
    // caller owns, so a chat somebody shared would list files it could not open.
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.includes("/file")
        ? { path: "/report.csv", content: "month,total", truncated: false }
        : workspace(),
    );

    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();
    await userEvent.click(await screen.findByRole("button", { name: /report\.csv/ }));

    await waitFor(() =>
      expect(vi.mocked(apiClient.get).mock.calls.map(([url]) => url)).toContain(
        "/conversations/c1/workspace/file?path=%2Freport.csv",
      ),
    );
  });

  it("offers the file as a download, asking the route for it as an attachment", async () => {
    Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
    // A stub rather than a real `Response`: jsdom's `Blob` is not the one its
    // `Response` constructor accepts, and this call only ever reads `blob()`.
    vi.mocked(apiClient.raw).mockResolvedValue({
      blob: async () => new Blob(["month,total"]),
    } as unknown as Response);
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.includes("/file")
        ? { path: "/report.csv", content: "month,total", truncated: false }
        : workspace(),
    );

    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();
    await userEvent.click(await screen.findByRole("button", { name: /report\.csv/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Download" }));

    expect(vi.mocked(apiClient.raw).mock.calls[0]?.[0]).toBe(
      "/conversations/c1/workspace/raw?path=%2Freport.csv&download=true",
    );
  });

  it("says a file was shortened, because the agent read all of it", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.includes("/file")
        ? { path: "/report.csv", content: "month", truncated: true }
        : workspace(),
    );

    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();
    await userEvent.click(await screen.findByRole("button", { name: /report\.csv/ }));

    await waitFor(() =>
      expect(
        screen.getByText("This has been shortened. The agent reads the whole file."),
      ).toBeVisible(),
    );
  });

  it("reports a file it could not read where the file was", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.includes("/file")) throw new Error("That file is not text");
      return workspace();
    });

    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();
    await userEvent.click(await screen.findByRole("button", { name: /report\.csv/ }));

    await waitFor(() => expect(screen.getByText("That file is not text")).toBeVisible());
  });

  it("shows nothing for a file the route answered nothing for", async () => {
    // A 204 or an empty body is not an empty file; an empty `<pre>` would say the
    // file is blank when what happened is that nobody answered.
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.includes("/file") ? null : workspace(),
    );

    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();
    await userEvent.click(await screen.findByRole("button", { name: /report\.csv/ }));

    await screen.findByRole("dialog");
    expect(screen.queryByRole("figure")).toBeNull();
  });

  it("reads bytes and megabytes in the units a person uses", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(
      workspace({
        items: [
          { path: "/small.txt", size: 12, is_dir: false },
          { path: "/big.csv", size: 2_097_152, is_dir: false },
          { path: "/unmeasured.bin", size: null, is_dir: false },
        ],
        bytes_total: 2_097_164,
      }),
    );

    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();

    await waitFor(() => expect(screen.getByText("TXT · 12 B")).toBeVisible());
    expect(screen.getByText("CSV · 2.0 MB")).toBeVisible();
    expect(screen.getByRole("button", { name: /unmeasured\.bin/ })).toBeVisible();
  });

  it("is a button in the corner until somebody opens it", async () => {
    // A permanent third column took space from every conversation, including the
    // ones where the agent keeps nothing worth looking at.
    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);

    expect(await screen.findByRole("button", { name: /^Show the files/ })).toBeVisible();
    expect(screen.queryByText("report.csv")).toBeNull();
  });

  it("says on the button how many files there are to see", async () => {
    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);

    expect(await screen.findByRole("button", { name: "Show the files (1)" })).toBeVisible();
  });

  it("still offers to open when the workspace is empty", async () => {
    // The count is what says there is something to look at; its absence must not
    // take the control away, or a workspace that fills up later is unreachable.
    vi.mocked(apiClient.get).mockResolvedValue(workspace({ items: [], total: 0 }));

    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);

    expect(await screen.findByRole("button", { name: "Show the files" })).toBeVisible();
  });

  it("closes again", async () => {
    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();
    await waitFor(() => expect(screen.getByText("report.csv")).toBeVisible());

    await userEvent.click(screen.getByRole("button", { name: "Close the file panel" }));

    expect(screen.queryByText("report.csv")).toBeNull();
  });

  it("explains a host that keeps no files on disk instead of alarming somebody", async () => {
    // Not red, and not beside "nothing yet": a service started with no
    // `workspace_root` is a configuration somebody chose, with a one-line fix the
    // message names. Saying "no files" as well would be the second wrong answer.
    vi.mocked(apiClient.get).mockResolvedValue(
      workspace({
        items: [],
        total: 0,
        backend: "service",
        unreadable_reason: "This host's files could not be read. No workspace root.",
      }),
    );

    draw(<WorkspaceFiles conversationId="c1" attachments={[]} revision={0} />);
    await openPanel();

    await waitFor(() => expect(screen.getByText(/No workspace root/)).toBeVisible());
    expect(screen.queryByText(/Nothing yet/)).toBeNull();
  });

  describe("files people attached", () => {
    const attachment = (overrides: Record<string, unknown> = {}) => ({
      id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
      filename: "invoice.pdf",
      mime_type: "application/pdf",
      file_type: "pdf",
      ...overrides,
    });

    it("lists one the agent has no copy of", async () => {
      // The case with no workspace at all: the agent cannot open it, and the person
      // who dragged it in still looks for it here.
      vi.mocked(apiClient.get).mockResolvedValue(
        workspace({ backend: "none", items: [], total: 0, bytes_total: 0 }),
      );

      draw(<WorkspaceFiles conversationId="c1" attachments={[attachment()]} revision={0} />);
      await openPanel();

      expect(screen.getByText("Attached to the chat")).toBeVisible();
      expect(screen.getByText("invoice.pdf")).toBeVisible();
    });

    it("counts them on the button beside the agent's own", async () => {
      draw(<WorkspaceFiles conversationId="c1" attachments={[attachment()]} revision={0} />);

      // One workspace file (the directory does not count) plus one attachment.
      expect(await screen.findByRole("button", { name: /Show the files \(2\)/ })).toBeVisible();
    });

    it("does not list one twice when the workspace already holds it", async () => {
      // `workspace_path` builds `/uploads/<first eight hex of the id>-<safe name>`, so
      // the prefix is what says these are the same file. A name match would collide
      // the moment two people attach `report.csv`, which is what the id is there for.
      vi.mocked(apiClient.get).mockResolvedValue(
        workspace({
          items: [{ path: "/uploads/aaaaaaaa-invoice.pdf", size: 120, is_dir: false }],
          total: 1,
        }),
      );

      draw(<WorkspaceFiles conversationId="c1" attachments={[attachment()]} revision={0} />);
      await openPanel();

      expect(screen.queryByText("Attached to the chat")).toBeNull();
      expect(screen.getByText("aaaaaaaa-invoice.pdf")).toBeVisible();
    });

    it("still lists a different file whose name happens to match", async () => {
      // Two people attaching `invoice.pdf` are two files, and the workspace holds one
      // of them. Matching on the name alone would have hidden the other.
      vi.mocked(apiClient.get).mockResolvedValue(
        workspace({
          items: [{ path: "/uploads/99999999-invoice.pdf", size: 120, is_dir: false }],
          total: 1,
        }),
      );

      draw(<WorkspaceFiles conversationId="c1" attachments={[attachment()]} revision={0} />);
      await openPanel();

      expect(screen.getByText("Attached to the chat")).toBeVisible();
      expect(screen.getByText("invoice.pdf")).toBeVisible();
    });

    it("opens one into the shared preview rather than the workspace viewer", async () => {
      // The workspace viewer reads through the conversation's workspace, which for an
      // attachment the agent never got is a request for a file that is not there. The
      // preview panel serves it from `/files/{id}`, which is what the attachment chips
      // on the messages already use.
      const { useFilePreviewStore } = await import("@/stores");
      vi.mocked(apiClient.get).mockResolvedValue(
        workspace({ backend: "none", items: [], total: 0, bytes_total: 0 }),
      );

      draw(<WorkspaceFiles conversationId="c1" attachments={[attachment()]} revision={0} />);
      await openPanel();
      await userEvent.click(screen.getByText("invoice.pdf"));

      expect(useFilePreviewStore.getState().file).toMatchObject({ filename: "invoice.pdf" });
    });
  });
});
