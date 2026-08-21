import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FilePreviewDialog } from "./file-preview-dialog";
import { useFilePreviewStore } from "@/stores";
import type { ChatMessageFile } from "@/types";

vi.mock("./markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));

let fetchMock: ReturnType<typeof vi.fn>;

function serve(body: string, { ok = true, status = 200, type = "text/plain" } = {}) {
  fetchMock = vi.fn().mockResolvedValue({
    ok,
    status,
    text: () => Promise.resolve(body),
    blob: () => Promise.resolve(new Blob([body], { type })),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function file(overrides: Partial<ChatMessageFile> = {}): ChatMessageFile {
  return {
    id: "f-1",
    filename: "invoice.pdf",
    mime_type: "application/pdf",
    file_type: "pdf",
    ...overrides,
  };
}

function Wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function open(one: Partial<ChatMessageFile> = {}, available?: ChatMessageFile[]) {
  const store = useFilePreviewStore.getState();
  store.setAvailable(available ?? [file(one)]);
  store.open(file(one));
  return render(<FilePreviewDialog />, { wrapper: Wrapper });
}

beforeEach(() => {
  useFilePreviewStore.getState().close();
  useFilePreviewStore.getState().setAvailable([]);
  Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
  serve("");
});

afterEach(() => vi.unstubAllGlobals());

/**
 * Opening an attachment from the chat.
 *
 * The dialog is `FileViewer`, which is where its chrome, its render branches and
 * its carousel are asserted. What belongs here is the wiring: that the store's
 * set reaches the viewer, that paging through it changes the file being fetched,
 * and that closing empties the store rather than leaving it open with nothing on
 * screen.
 */
describe("the chat's file dialog", () => {
  it("renders nothing at all while no file is open", () => {
    const { container } = render(<FilePreviewDialog />, { wrapper: Wrapper });

    expect(container).toBeEmptyDOMElement();
  });

  it("shows the file itself, through the shared renderer", async () => {
    serve("# Notes");
    open({ filename: "notes.md", mime_type: "text/markdown" });

    expect(await screen.findByTestId("markdown")).toHaveTextContent("# Notes");
  });

  it("sends the session cookie with the fetch, because the file is behind it", async () => {
    serve("a,b");
    open({ filename: "report.csv", mime_type: "text/csv" });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledWith("/api/files/f-1", { credentials: "include" });
  });

  it("says a file could not be fetched rather than rendering empty", async () => {
    // Opened from a message; the file behind it can have been deleted, or belong
    // to a conversation somebody lost access to.
    serve("", { ok: false, status: 404 });
    open({ filename: "notes.txt", mime_type: "text/plain" });

    expect(await screen.findByText("HTTP 404")).toBeInTheDocument();
  });

  it("offers no carousel for a single attachment", () => {
    open();

    expect(screen.queryByRole("button", { name: "Next file" })).toBeNull();
  });

  it("pages through the message's other attachments without closing", async () => {
    // The whole point of the set: reaching the third of five used to mean closing
    // the panel, finding the message again and clicking the next card.
    const notes = file({ id: "f-2", filename: "notes.txt", mime_type: "text/plain" });
    serve("plain text");
    open({}, [file(), notes]);

    await userEvent.click(screen.getByRole("button", { name: "Next file" }));

    expect(screen.getByText(/2 of 2/)).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/files/f-2", { credentials: "include" }),
    );
  });

  it("jumps to the file whose chip was clicked", async () => {
    const notes = file({ id: "f-2", filename: "notes.txt", mime_type: "text/plain" });
    serve("plain text");
    open({}, [file(), notes]);

    await userEvent.click(screen.getByRole("button", { name: /notes\.txt/ }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/files/f-2", { credentials: "include" }),
    );
  });

  it("empties the store when it closes, so it cannot reopen on nothing", async () => {
    open();

    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(useFilePreviewStore.getState().openId).toBeNull();
  });
});
