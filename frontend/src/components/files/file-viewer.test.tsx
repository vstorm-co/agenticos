import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FileViewer, type ViewerFile } from "./file-viewer";
import type { FileAccess } from "@/lib/file-access";

vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));

function access(overrides: Partial<FileAccess> = {}): FileAccess {
  return {
    textKey: ["text", Math.random()],
    bytesKey: ["bytes", Math.random()],
    readText: () => Promise.resolve({ content: "# Report", truncated: false }),
    readBytes: () => Promise.resolve(new Blob(["%PDF-"], { type: "application/pdf" })),
    download: () => Promise.resolve(),
    ...overrides,
  };
}

function open(
  file: ViewerFile,
  {
    over = {},
    ...rest
  }: { over?: Partial<FileAccess> } & Partial<
    Omit<Parameters<typeof FileViewer>[0], "file" | "access">
  > = {},
) {
  function Wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return render(
    <FileViewer file={file} access={access(over)} onClose={rest.onClose ?? (() => {})} {...rest} />,
    { wrapper: Wrapper },
  );
}

beforeEach(() => {
  Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
});

/**
 * The header, which is the visible half of #136.
 *
 * It used to be the name, then the *path* in monospace underneath - and for a file at
 * a workspace root the path is the name, so the dialog opened saying `test.md` twice
 * and nothing else. No size, no type, no modification time.
 */
describe("what the header says about a file", () => {
  it("names it, then says what kind and how big", () => {
    open({ name: "report.md", path: "/report.md", size: 3 });

    expect(screen.getByRole("heading", { name: /report\.md/ })).toBeInTheDocument();
    expect(screen.getByText("MD · 3 B")).toBeInTheDocument();
  });

  it("says when it changed, where the origin records one", () => {
    const twoHoursAgo = new Date(Date.now() - 2 * 3600 * 1000).toISOString();
    open({ name: "handbook.pdf", size: 2048, modifiedAt: twoHoursAgo });

    expect(screen.getByText("PDF · 2.0 KB · modified 2h ago")).toBeInTheDocument();
  });

  it("leaves out what the origin does not know", () => {
    // A workspace listing carries no modification time at all, and a size can be null.
    open({ name: "report.md" });

    expect(screen.getByText("MD")).toBeInTheDocument();
  });

  it("names the kind for a file with no extension to show", () => {
    open({ name: "Makefile", mimeType: "text/x-makefile" });

    expect(screen.getByText("Text")).toBeInTheDocument();
  });

  it("ignores a modification time it cannot read", () => {
    open({ name: "report.md", modifiedAt: "not a date" });

    expect(screen.getByText("MD")).toBeInTheDocument();
  });

  it("shows the path when there are folders in it", () => {
    // A workspace holds `out/report.csv` beside `report.csv` often enough that the
    // name alone is ambiguous.
    open({ name: "report.csv", path: "/out/report.csv" });

    expect(screen.getByText("/out/report.csv")).toBeInTheDocument();
  });

  it("does not show the path when it is the name with a slash on it", () => {
    open({ name: "report.csv", path: "/report.csv" });

    expect(screen.queryByText("/report.csv")).toBeNull();
  });

  it("does not show a path it was never given", () => {
    // Which is every knowledge base document: it has a filename and no folders.
    open({ name: "handbook.pdf" });

    expect(screen.getByRole("heading", { name: /handbook\.pdf/ })).toBeInTheDocument();
  });
});

/**
 * Preview and source, wherever both are meaningful.
 *
 * Markdown *and* HTML, where the workspace dialog offered it for Markdown alone - and
 * a table hides which delimiter a CSV used, so that counts too.
 */
describe("the views a file offers", () => {
  it("offers the characters as well, for a file whose preview transforms it", async () => {
    open({ name: "report.md" });

    expect(await screen.findByTestId("markdown")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Source" }));

    expect(screen.queryByTestId("markdown")).toBeNull();
    expect(screen.getByText("# Report")).toBeInTheDocument();
  });

  it("offers it for an HTML page too", () => {
    open({ name: "report.html" });

    expect(screen.getByRole("tab", { name: "Source" })).toBeInTheDocument();
  });

  it("offers no toggle where there would be nothing to toggle to", () => {
    open({ name: "handbook.pdf" });

    expect(screen.queryByRole("tab")).toBeNull();
  });

  it("opens a view the surface added, without knowing what it is", async () => {
    // A knowledge base document's parsed text. Ingestion is that surface's business,
    // and nothing else here knows or should learn there is a parser at all.
    open(
      { name: "handbook.pdf" },
      {
        extraTabs: [{ value: "parsed", label: "Parsed", content: <p>what the parser read</p> }],
      },
    );

    await userEvent.click(screen.getByRole("tab", { name: "Parsed" }));

    expect(screen.getByText("what the parser read")).toBeInTheDocument();
  });

  it("puts an added view beside the ones the file has", () => {
    open(
      { name: "report.md" },
      { extraTabs: [{ value: "parsed", label: "Parsed", content: null }] },
    );

    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Preview",
      "Source",
      "Parsed",
    ]);
  });
});

describe("the things somebody does with a file besides looking at it", () => {
  it("saves it", async () => {
    const download = vi.fn().mockResolvedValue(undefined);
    open({ name: "report.md" }, { over: { download } });

    await userEvent.click(screen.getByRole("button", { name: /Download/ }));

    expect(download).toHaveBeenCalled();
  });

  it("opens it in a tab of its own", async () => {
    const windowOpen = vi.fn();
    vi.stubGlobal("open", windowOpen);
    open({ name: "handbook.pdf" });

    await userEvent.click(screen.getByRole("button", { name: "Open in a new tab" }));

    await waitFor(() => expect(windowOpen).toHaveBeenCalled());
    vi.unstubAllGlobals();
  });

  it("says why one of them was refused, rather than doing nothing", async () => {
    // A binary in a container-backed workspace is read through an archive that can
    // only read text, so the API answers 400.
    open(
      { name: "report.md" },
      { over: { download: () => Promise.reject(new Error("This host can only read text")) } },
    );

    await userEvent.click(screen.getByRole("button", { name: /Download/ }));

    await waitFor(() =>
      expect(screen.getByText("This host can only read text")).toBeInTheDocument(),
    );
  });

  it("closes", async () => {
    const onClose = vi.fn();
    open({ name: "report.md" }, { onClose });

    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(onClose).toHaveBeenCalled();
  });
});

/**
 * Sized to the content, with a floor.
 *
 * A three-byte file used to open the same 900-pixel box as a report. The width is the
 * only thing the kind decides, because a PDF read in a column as wide as a paragraph
 * is a PDF nobody can read.
 */
describe("how big the dialog is", () => {
  const width = () => screen.getByRole("dialog").className;

  it("is wide for what a browser renders as a document", () => {
    for (const name of ["handbook.pdf", "chart.png", "demo.mp4", "rows.csv"]) {
      const { unmount } = open({ name });
      expect(width()).toContain("sm:max-w-5xl");
      unmount();
    }
  });

  it("is narrow for what reads better narrow", () => {
    open({ name: "report.md" });

    expect(width()).toContain("sm:max-w-3xl");
  });

  it("gives the body a floor as well as a ceiling", () => {
    // A three-byte file gets a small box; a report grows to 70% of the viewport
    // rather than pushing the dialog off the screen.
    const { container } = open({ name: "report.md" });

    expect(container.ownerDocument.querySelector(".min-h-16")).toHaveClass("max-h-[70vh]");
  });
});
