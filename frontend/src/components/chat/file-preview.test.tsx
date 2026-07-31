import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FilePreviewCard, extOf, iconFor, previewKind } from "./file-preview-card";
import { FilePreviewPanel } from "./file-preview-panel";
import { useFilePreviewStore } from "@/stores";
import type { ChatMessageFile } from "@/types";

vi.mock("./markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));

let fetchMock: ReturnType<typeof vi.fn>;

function serve(body: string, { ok = true, status = 200 } = {}) {
  fetchMock = vi.fn().mockResolvedValue({ ok, status, text: () => Promise.resolve(body) });
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

function card(props: Partial<Parameters<typeof FilePreviewCard>[0]> = {}) {
  return render(
    <FilePreviewCard
      kind="binary"
      url="/api/files/f-1"
      downloadUrl="/api/files/f-1?disposition=attachment"
      filename="thing.bin"
      ext={null}
      {...props}
    />,
  );
}

beforeEach(() => {
  useFilePreviewStore.getState().close();
  localStorage.clear();
  serve("");
});

afterEach(() => vi.unstubAllGlobals());

/**
 * Previewing an attachment.
 *
 * Which viewer opens is decided from the MIME type first and the extension
 * second, because a browser upload of an unknown type sends
 * `application/octet-stream` and the filename is then the only clue. The
 * fallbacks matter more than the happy paths here: a file with no preview offers
 * a download rather than an empty panel, and a file that could not be fetched
 * says so rather than rendering as empty.
 */
describe("deciding which viewer to open", () => {
  it("reads an extension, in lower case", () => {
    expect(extOf("Invoice.PDF")).toBe("pdf");
    expect(extOf("archive.tar.gz")).toBe("gz");
  });

  it("has no extension for a file with none", () => {
    // `Makefile`, `LICENSE` - and the MIME type is what decides those.
    expect(extOf("Makefile")).toBeNull();
    expect(extOf("weird.")).toBeNull();
  });

  it("trusts the MIME type when it says something", () => {
    expect(previewKind("image/png", null)).toBe("image");
    expect(previewKind("application/pdf", null)).toBe("pdf");
    expect(previewKind("audio/mpeg", null)).toBe("audio");
    expect(previewKind("video/mp4", null)).toBe("video");
    expect(previewKind("text/csv", null)).toBe("csv");
    expect(previewKind("text/html", null)).toBe("html");
    expect(previewKind("application/json", null)).toBe("json");
    expect(previewKind("text/markdown", null)).toBe("markdown");
    expect(previewKind("text/plain", null)).toBe("text");
  });

  it("falls back to the extension when the type says nothing useful", () => {
    // Which is every drag-and-drop upload of an unrecognised type.
    const octet = "application/octet-stream";
    expect(previewKind(octet, "png")).toBe("image");
    expect(previewKind(octet, "pdf")).toBe("pdf");
    expect(previewKind(octet, "mp3")).toBe("audio");
    expect(previewKind(octet, "webm")).toBe("video");
    expect(previewKind(octet, "tsv")).toBe("csv");
    expect(previewKind(octet, "htm")).toBe("html");
    expect(previewKind(octet, "jsonc")).toBe("json");
    expect(previewKind(octet, "mdx")).toBe("markdown");
    expect(previewKind(octet, "py")).toBe("code");
    expect(previewKind(octet, "log")).toBe("text");
  });

  it("is case-insensitive about the type", () => {
    expect(previewKind("IMAGE/PNG", null)).toBe("image");
  });

  it("calls anything it cannot preview binary", () => {
    expect(previewKind("application/octet-stream", "bin")).toBe("binary");
    expect(previewKind(undefined, null)).toBe("binary");
  });

  it("picks an icon that says what kind of file it is", () => {
    // Four icons across eleven kinds: the point is a glance, not a taxonomy, so
    // the three media kinds are distinct and everything textual shares one.
    const distinct = new Set([iconFor("image"), iconFor("audio"), iconFor("video")]);
    expect(distinct.size).toBe(3);

    expect(iconFor("code")).toBe(iconFor("json"));
    expect(iconFor("code")).toBe(iconFor("html"));
    expect(iconFor("binary")).toBe(iconFor("text"));
    expect(iconFor("pdf")).toBe(iconFor("text"));
    expect(iconFor("csv")).toBe(iconFor("text"));
    expect(iconFor("markdown")).toBe(iconFor("text"));
  });
});

describe("the viewers", () => {
  it("shows an image with the filename as its alternative text", () => {
    card({ kind: "image", filename: "logo.png" });

    expect(screen.getByRole("img", { name: "logo.png" })).toHaveAttribute("src", "/api/files/f-1");
  });

  it("renders a PDF in a frame, with the reader's own chrome collapsed", () => {
    card({ kind: "pdf", filename: "invoice.pdf" });

    expect(screen.getByTitle("invoice.pdf")).toHaveAttribute(
      "src",
      "/api/files/f-1#toolbar=0&navpanes=0",
    );
  });

  it("plays audio and video with controls", () => {
    const { container, unmount } = card({ kind: "audio", filename: "call.mp3" });
    expect(container.querySelector("audio")).toHaveAttribute("controls");
    expect(screen.getByText("call.mp3")).toBeInTheDocument();
    unmount();

    const video = card({ kind: "video", filename: "demo.mp4" });
    expect(video.container.querySelector("video")).toHaveAttribute("controls");
  });

  it("offers a download for a file it cannot show", () => {
    card({ kind: "binary", filename: "archive.bin" });

    expect(screen.getByText("No inline preview for this file type.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download/ })).toHaveAttribute(
      "href",
      "/api/files/f-1?disposition=attachment",
    );
  });

  it("sandboxes an HTML file so nothing in it can run", async () => {
    // Somebody's uploaded page, rendered to be looked at. Scripts, forms and
    // same-origin access are all things it has no business having.
    serve("<p>hello</p>");
    card({ kind: "html" });

    const frame = await screen.findByTitle("HTML preview");
    expect(frame).toHaveAttribute("sandbox", "");
    expect(frame).toHaveAttribute("srcdoc", "<p>hello</p>");
  });

  it("pretty-prints JSON, and shows it as it stands when it does not parse", async () => {
    serve('{"a":1}');
    const { unmount } = card({ kind: "json" });
    expect(await screen.findByText(/"a": 1/)).toBeInTheDocument();
    unmount();

    serve("{not json");
    card({ kind: "json" });
    expect(await screen.findByText("{not json")).toBeInTheDocument();
  });

  it("renders Markdown as Markdown", async () => {
    serve("# Title");
    card({ kind: "markdown" });

    expect(await screen.findByTestId("markdown")).toHaveTextContent("# Title");
  });

  it("fences code with the language its extension implies", async () => {
    // Reusing the Markdown pipeline is what gives syntax highlighting for free.
    serve("print(1)");
    card({ kind: "code", ext: "py" });

    expect(await screen.findByTestId("markdown")).toHaveTextContent("```python");
  });

  it("fences a code file whose language nobody mapped as plain text", async () => {
    serve("something");
    card({ kind: "code", ext: "unknownlang" });

    expect(await screen.findByTestId("markdown")).toHaveTextContent("```text");
  });

  it("shows plain text as it is, preserving its whitespace", async () => {
    serve("line one\n  line two");
    card({ kind: "text" });

    expect(await screen.findByText(/line one/)).toHaveClass("whitespace-pre");
  });

  it("says a file could not be fetched rather than rendering empty", async () => {
    // The panel is opened from a message; the file behind it can have been
    // deleted, or belong to a conversation somebody lost access to.
    serve("", { ok: false, status: 404 });
    card({ kind: "text" });

    expect(await screen.findByText("Couldn't load preview")).toBeInTheDocument();
    expect(screen.getByText("HTTP 404")).toBeInTheDocument();
  });

  it("says so when the fetch itself failed", async () => {
    fetchMock = vi.fn().mockRejectedValue(new Error("offline"));
    vi.stubGlobal("fetch", fetchMock);
    card({ kind: "html" });

    expect(await screen.findByText("offline")).toBeInTheDocument();
  });

  it("says something even when the failure carries no message", async () => {
    // Every viewer that fetches has the same fallback, and each has its own copy
    // of it - so each is asserted.
    for (const kind of ["csv", "html", "text"] as const) {
      fetchMock = vi.fn().mockRejectedValue("boom");
      vi.stubGlobal("fetch", fetchMock);
      const { unmount } = card({ kind });

      expect(await screen.findByText("Failed to load")).toBeInTheDocument();
      unmount();
    }
  });

  it("reports the status for every viewer that fetches", async () => {
    for (const kind of ["csv", "html", "text"] as const) {
      serve("", { ok: false, status: 403 });
      const { unmount } = card({ kind });

      expect(await screen.findByText("HTTP 403")).toBeInTheDocument();
      unmount();
    }
  });

  it("fences a code file with no extension at all as plain text", async () => {
    // `Makefile` reaches the code viewer through its MIME type and has nothing to
    // look up.
    serve("all: build");
    card({ kind: "code", ext: null });

    expect(await screen.findByTestId("markdown")).toHaveTextContent("```text");
  });

  it("writes nothing into a viewer that has already been closed", async () => {
    // Closing the panel mid-fetch used to warn about setting state on an unmounted
    // component; the guard is why it does not.
    let release: (value: unknown) => void = () => {};
    fetchMock = vi.fn().mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { unmount } = card({ kind: "text" });

    unmount();
    release({ ok: true, status: 200, text: () => Promise.resolve("late") });

    await waitFor(() => expect(screen.queryByText("late")).toBeNull());
  });

  it("sends the session cookie with the fetch, because the file is behind it", async () => {
    serve("a,b");
    card({ kind: "csv" });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledWith("/api/files/f-1", { credentials: "include" });
  });
});

describe("the CSV table", () => {
  it("uses the first row as the header", async () => {
    serve("name,total\nAcme,42");
    card({ kind: "csv" });

    expect(await screen.findByRole("columnheader", { name: "name" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Acme" })).toBeInTheDocument();
  });

  it("reads a quoted field containing a comma", async () => {
    // The reason there is a parser here at all rather than a `split(",")`.
    serve('name,note\n"Acme, Inc.",fine');
    card({ kind: "csv" });

    expect(await screen.findByRole("cell", { name: "Acme, Inc." })).toBeInTheDocument();
  });

  it("reads an escaped quote inside a quoted field", async () => {
    serve('note\n"He said ""no"""');
    card({ kind: "csv" });

    expect(await screen.findByRole("cell", { name: 'He said "no"' })).toBeInTheDocument();
  });

  it("reads a newline inside a quoted field as part of it", async () => {
    serve('note\n"line one\nline two"');
    card({ kind: "csv" });

    const cell = await screen.findByRole("cell");
    expect(cell.textContent).toBe("line one\nline two");
  });

  it("reads tab-separated files too", async () => {
    serve("name\ttotal\nAcme\t42");
    card({ kind: "csv" });

    expect(await screen.findByRole("columnheader", { name: "name" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Acme" })).toBeInTheDocument();
  });

  it("reads Windows line endings", async () => {
    serve("name,total\r\nAcme,42\r\n");
    card({ kind: "csv" });

    expect(await screen.findByRole("columnheader", { name: "name" })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(2);
  });

  it("says a file is empty rather than showing an empty table", async () => {
    serve("");
    card({ kind: "csv" });

    expect(await screen.findByText("Empty file")).toBeInTheDocument();
  });

  it("shows the first five hundred rows and says how many there are", async () => {
    // A hundred thousand rows in the DOM is a panel that never opens.
    const rows = ["name", ...Array.from({ length: 600 }, (_, index) => `row-${index}`)].join("\n");
    serve(rows);
    card({ kind: "csv" });

    expect(await screen.findByText(/Showing 500 of 600 rows/)).toBeInTheDocument();
    // 500 body rows plus the header.
    expect(screen.getAllByRole("row")).toHaveLength(501);
  });

  it("says nothing about truncation for a file that fits", async () => {
    serve("name\nAcme");
    card({ kind: "csv" });

    await screen.findByRole("columnheader", { name: "name" });
    expect(screen.queryByText(/Showing/)).toBeNull();
  });
});

describe("the preview panel", () => {
  function open(overrides: Partial<ChatMessageFile> = {}) {
    useFilePreviewStore.getState().open(file(overrides));
    return render(<FilePreviewPanel />);
  }

  it("renders nothing at all while no file is open", () => {
    const { container } = render(<FilePreviewPanel />);

    expect(container).toBeEmptyDOMElement();
  });

  it("names the file, and says what kind it is", () => {
    open();

    // Twice: the header names it, and the PDF frame is titled with it.
    expect(screen.getAllByTitle("invoice.pdf")).toHaveLength(2);
    expect(screen.getByText("pdf")).toBeInTheDocument();
  });

  it("falls back to the MIME type for a file with no extension", () => {
    open({ filename: "Makefile", mime_type: "text/x-makefile" });

    expect(screen.getByText("text/x-makefile")).toBeInTheDocument();
  });

  it("says only 'file' when it knows neither", () => {
    open({ filename: "Makefile", mime_type: undefined as unknown as string });

    expect(screen.getByText("file")).toBeInTheDocument();
  });

  it("offers the file inline in a new tab and as a download", () => {
    // Two links, two dispositions: the tab renders it, the download saves it.
    open();

    expect(screen.getByTitle("Open in new tab")).toHaveAttribute("href", "/api/files/f-1");
    expect(screen.getByTitle("Download")).toHaveAttribute(
      "href",
      "/api/files/f-1?disposition=attachment",
    );
  });

  it("opens the new tab without a handle back to this one", () => {
    open();

    expect(screen.getByTitle("Open in new tab")).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("closes", async () => {
    open();

    await userEvent.click(screen.getByRole("button", { name: "Close preview" }));

    expect(useFilePreviewStore.getState().file).toBeNull();
  });

  it("opens at its default width", () => {
    open();

    expect(screen.getByLabelText("File preview")).toHaveStyle({ width: "480px" });
  });

  it("reopens at the width somebody dragged it to", () => {
    // The panel competes with the transcript for the window; a width nobody
    // chose is a width they have to set on every reload.
    localStorage.setItem("filePreviewPanelWidth", "700");

    open();

    expect(screen.getByLabelText("File preview")).toHaveStyle({ width: "700px" });
  });

  it("clamps a stored width that would leave no room for either pane", () => {
    localStorage.setItem("filePreviewPanelWidth", "5000");
    const { unmount } = open();
    expect(screen.getByLabelText("File preview")).toHaveStyle({ width: "1100px" });
    unmount();

    localStorage.setItem("filePreviewPanelWidth", "10");
    open();
    expect(screen.getByLabelText("File preview")).toHaveStyle({ width: "320px" });
  });

  it("ignores a stored width that is not a number", () => {
    localStorage.setItem("filePreviewPanelWidth", "not a number");

    open();

    expect(screen.getByLabelText("File preview")).toHaveStyle({ width: "480px" });
  });

  it("resizes on a drag, and remembers where it was let go", () => {
    open();
    const handle = screen.getByRole("separator", { name: "Resize file preview" });

    fireEvent.mouseDown(handle);
    // Width is the distance from the cursor to the right edge.
    fireEvent.mouseMove(window, { clientX: window.innerWidth - 640 });
    expect(screen.getByLabelText("File preview")).toHaveStyle({ width: "640px" });

    fireEvent.mouseUp(window);
    expect(localStorage.getItem("filePreviewPanelWidth")).toBe("640");
  });

  it("keeps the panel usable however far the cursor goes", () => {
    open();
    fireEvent.mouseDown(screen.getByRole("separator", { name: "Resize file preview" }));

    fireEvent.mouseMove(window, { clientX: window.innerWidth });
    expect(screen.getByLabelText("File preview")).toHaveStyle({ width: "320px" });

    fireEvent.mouseMove(window, { clientX: -5000 });
    expect(screen.getByLabelText("File preview")).toHaveStyle({ width: "1100px" });
  });

  it("stops resizing once the mouse is released", () => {
    open();
    fireEvent.mouseDown(screen.getByRole("separator", { name: "Resize file preview" }));
    fireEvent.mouseUp(window);

    fireEvent.mouseMove(window, { clientX: window.innerWidth - 900 });

    expect(screen.getByLabelText("File preview")).toHaveStyle({ width: "480px" });
  });

  it("survives a browser that refuses to remember the width", () => {
    // Private mode, or a full quota: the drag still has to work.
    open();
    const setItem = vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });

    fireEvent.mouseDown(screen.getByRole("separator", { name: "Resize file preview" }));
    fireEvent.mouseMove(window, { clientX: window.innerWidth - 600 });
    fireEvent.mouseUp(window);

    expect(screen.getByLabelText("File preview")).toHaveStyle({ width: "600px" });
    setItem.mockRestore();
  });

  it("shows the viewer for the file it is previewing", () => {
    open({ filename: "logo.png", mime_type: "image/png" });

    expect(
      within(screen.getByLabelText("File preview")).getByRole("img", { name: "logo.png" }),
    ).toBeInTheDocument();
  });
});
