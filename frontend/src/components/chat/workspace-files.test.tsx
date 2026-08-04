import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
      { path: "/report.csv", size: 2048, is_dir: false },
      { path: "/out", size: null, is_dir: true },
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
 * Two properties carry it. It is absent rather than empty for an agent with no
 * workspace, which is most of them - a permanent empty box beside every chat is
 * worse than no panel. And it says whose files these are, because under `agent`
 * scope one workspace is shared and finding a file you did not create reads as a
 * leak until something on screen explains it.
 */
describe("the workspace panel", () => {
  it("lists what the agent is keeping as tiles, with what each file weighs", async () => {
    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
    await openPanel();

    // The name, not the path: a 288-pixel column of monospace paths is unreadable,
    // and the whole path is on the tile's title and in the viewer it opens.
    await waitFor(() => expect(screen.getByText("report.csv")).toBeVisible());
    expect(screen.getByText("2 KiB")).toBeVisible();
  });

  it("says whose files these are", async () => {
    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
    await openPanel();

    await waitFor(() => expect(screen.getByText(/This conversation/)).toBeVisible());
  });

  it("reports what a stored workspace is holding in total", async () => {
    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
    await openPanel();

    await waitFor(() => expect(screen.getByText(/2 KiB stored/)).toBeVisible());
  });

  it("is absent entirely for an agent that keeps no files", async () => {
    // Not an empty panel: most agents have no workspace, and a box saying
    // "nothing yet" beside every chat forever is furniture, not information.
    vi.mocked(apiClient.get).mockResolvedValue(
      workspace({ backend: "none", items: [], total: 0, bytes_total: 0 }),
    );

    const { container } = draw(<WorkspaceFiles conversationId="c1" revision={0} />);

    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("draws nothing until the listing has answered", async () => {
    // The flicker this fixes: the button used to render while the query was in
    // flight, so the first message of a conversation showed it as the id arrived,
    // hid it when the listing said there was no workspace yet - there is no row
    // until the first turn flushes one - and showed it again when the turn ended.
    // Three states in one turn for a panel whose job is to sit still.
    let answer: (value: unknown) => void = () => {};
    vi.mocked(apiClient.get).mockImplementation(() => new Promise((resolve) => (answer = resolve)));

    const { container } = draw(<WorkspaceFiles conversationId="c1" revision={0} />);

    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();

    answer(workspace());
    expect(await screen.findByRole("button", { name: /^Show the files/ })).toBeVisible();
  });

  it("is absent before a conversation exists", () => {
    const { container } = draw(<WorkspaceFiles conversationId={null} revision={0} />);

    expect(container).toBeEmptyDOMElement();
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("does not list a directory as a file", async () => {
    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
    await openPanel();

    await waitFor(() => expect(screen.getByText("report.csv")).toBeVisible());
    expect(screen.queryByText("out")).toBeNull();
  });

  it("says the workspace is empty when it is, rather than showing nothing", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(workspace({ items: [], total: 0, bytes_total: 0 }));

    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
    await openPanel();

    await waitFor(() => expect(screen.getByText(/Nothing yet/)).toBeVisible());
  });

  it("reports a workspace it could not read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("The sandbox service is unreachable"));

    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
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
        <WorkspaceFiles conversationId="c1" revision={0} />
      </QueryClientProvider>,
    );
    await openPanel();
    await waitFor(() => expect(screen.getByText("report.csv")).toBeVisible());
    const before = vi.mocked(apiClient.get).mock.calls.length;

    rerender(
      <QueryClientProvider client={client}>
        <WorkspaceFiles conversationId="c1" revision={1} />
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

    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
    await openPanel();

    await userEvent.click(await screen.findByRole("button", { name: /report\.csv/ }));
    await waitFor(() => expect(screen.getByText("month,total")).toBeVisible());
    expect(screen.getByRole("dialog")).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("reads a file through its conversation, which is what a shared chat can do", async () => {
    // Not through the workspace's own id: that route is scoped to conversations the
    // caller owns, so a chat somebody shared would list files it could not open.
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.includes("/file")
        ? { path: "/report.csv", content: "month,total", truncated: false }
        : workspace(),
    );

    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
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

    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
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

    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
    await openPanel();
    await userEvent.click(await screen.findByRole("button", { name: /report\.csv/ }));

    await waitFor(() => expect(screen.getByText(/Shortened/)).toBeVisible());
  });

  it("reports a file it could not read where the file was", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.includes("/file")) throw new Error("That file is not text");
      return workspace();
    });

    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
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

    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
    await openPanel();
    await userEvent.click(await screen.findByRole("button", { name: /report\.csv/ }));

    await screen.findByRole("dialog");
    expect(screen.queryByRole("figure")).toBeNull();
  });

  it("reads bytes and megabytes in their own units", async () => {
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

    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
    await openPanel();

    await waitFor(() => expect(screen.getByText("12 B")).toBeVisible());
    expect(screen.getByText("2.0 MiB")).toBeVisible();
    expect(screen.getByRole("button", { name: /unmeasured\.bin/ })).toBeVisible();
  });

  it("is a button in the corner until somebody opens it", async () => {
    // A permanent third column took space from every conversation, including the
    // ones where the agent keeps nothing worth looking at.
    draw(<WorkspaceFiles conversationId="c1" revision={0} />);

    expect(await screen.findByRole("button", { name: /^Show the files/ })).toBeVisible();
    expect(screen.queryByText("report.csv")).toBeNull();
  });

  it("says on the button how many files there are to see", async () => {
    draw(<WorkspaceFiles conversationId="c1" revision={0} />);

    expect(await screen.findByRole("button", { name: "Show the files (1)" })).toBeVisible();
  });

  it("still offers to open when the workspace is empty", async () => {
    // The count is what says there is something to look at; its absence must not
    // take the control away, or a workspace that fills up later is unreachable.
    vi.mocked(apiClient.get).mockResolvedValue(workspace({ items: [], total: 0 }));

    draw(<WorkspaceFiles conversationId="c1" revision={0} />);

    expect(await screen.findByRole("button", { name: "Show the files" })).toBeVisible();
  });

  it("closes again", async () => {
    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
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

    draw(<WorkspaceFiles conversationId="c1" revision={0} />);
    await openPanel();

    await waitFor(() => expect(screen.getByText(/No workspace root/)).toBeVisible());
    expect(screen.queryByText(/Nothing yet/)).toBeNull();
  });
});
