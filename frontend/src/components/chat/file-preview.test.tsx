import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FilePreviewPanel } from "./file-preview-panel";
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

function open(overrides: Partial<ChatMessageFile> = {}) {
  useFilePreviewStore.getState().open(file(overrides));
  return render(<FilePreviewPanel />, { wrapper: Wrapper });
}

beforeEach(() => {
  useFilePreviewStore.getState().close();
  localStorage.clear();
  Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
  serve("");
});

afterEach(() => vi.unstubAllGlobals());

/**
 * Previewing an attachment.
 *
 * A panel rather than a dialog, and that is the only thing that distinguishes it from
 * every other file surface now: an attachment is read *beside* the message carrying
 * it, at whatever width the reader drags it to. What it shows is `FileContent`, which
 * is why the render branches are asserted in `components/files` and not here - this
 * was a fourth implementation with its own kind table, its own icon set and its own
 * copy of every viewer.
 */
describe("the preview panel", () => {
  it("renders nothing at all while no file is open", () => {
    const { container } = render(<FilePreviewPanel />, { wrapper: Wrapper });

    expect(container).toBeEmptyDOMElement();
  });

  it("names the file, and says what kind it is", () => {
    open();

    expect(screen.getByTitle("invoice.pdf")).toBeInTheDocument();
    expect(screen.getByText("pdf")).toBeInTheDocument();
  });

  it("falls back to the MIME type for a file with no extension", () => {
    open({ filename: "Makefile", mime_type: "text/x-makefile" });

    expect(screen.getByText("text/x-makefile")).toBeInTheDocument();
  });

  it("names the kind when it knows neither", () => {
    open({ filename: "Makefile", mime_type: undefined as unknown as string });

    expect(screen.getByText("File")).toBeInTheDocument();
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
    // The panel is opened from a message; the file behind it can have been deleted,
    // or belong to a conversation somebody lost access to.
    serve("", { ok: false, status: 404 });
    open({ filename: "notes.txt", mime_type: "text/plain" });

    expect(await screen.findByText("HTTP 404")).toBeInTheDocument();
  });

  it("closes", async () => {
    open();

    await userEvent.click(screen.getByRole("button", { name: "Close preview" }));

    expect(useFilePreviewStore.getState().file).toBeNull();
  });

  it("saves the file, and says so when it cannot", async () => {
    serve("", { ok: false, status: 403 });
    open();

    await userEvent.click(screen.getByTitle("Download"));

    expect(await screen.findByText("HTTP 403")).toBeInTheDocument();
  });

  it("opens the file in a tab of its own", async () => {
    const windowOpen = vi.fn();
    vi.stubGlobal("open", windowOpen);
    serve("%PDF-");
    open();

    await userEvent.click(screen.getByTitle("Open in new tab"));

    await waitFor(() => expect(windowOpen).toHaveBeenCalled());
  });

  it("starts clean when a different file is selected", async () => {
    // Keyed on the id, so the previous attachment's failure does not sit in the
    // header of the next one.
    serve("", { ok: false, status: 403 });
    open();
    await userEvent.click(screen.getByTitle("Download"));
    await screen.findByText("HTTP 403");

    serve("# Notes");
    useFilePreviewStore.getState().open(file({ id: "f-2", filename: "notes.md" }));

    await waitFor(() => expect(screen.queryByText("HTTP 403")).toBeNull());
  });
});

describe("resizing the panel", () => {
  /** Drag the separator to a viewport-relative x, which is how width is derived. */
  function drag(toClientX: number) {
    fireEvent.mouseDown(screen.getByRole("separator"));
    fireEvent.mouseMove(window, { clientX: toClientX });
    fireEvent.mouseUp(window);
  }

  it("remembers the width across sessions", () => {
    open();

    drag(window.innerWidth - 600);

    expect(localStorage.getItem("filePreviewPanelWidth")).toBe("600");
  });

  it("keeps the width inside bounds a panel is still usable at", () => {
    open();

    drag(window.innerWidth - 10);

    expect(localStorage.getItem("filePreviewPanelWidth")).toBe("320");
  });

  it("reads the remembered width as the first paint, not a frame later", () => {
    localStorage.setItem("filePreviewPanelWidth", "700");
    open();

    expect(screen.getByLabelText("File preview")).toHaveStyle({ width: "700px" });
  });

  it("falls back to the default when the remembered width is not a number", () => {
    localStorage.setItem("filePreviewPanelWidth", "wide please");
    open();

    expect(screen.getByLabelText("File preview")).toHaveStyle({ width: "480px" });
  });

  it("survives a browser that refuses to store anything", () => {
    // Private mode, or a full quota. Dropping persistence is the right answer; a
    // thrown error mid-drag is not.
    open();
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });

    expect(() => drag(window.innerWidth - 600)).not.toThrow();
  });
});
