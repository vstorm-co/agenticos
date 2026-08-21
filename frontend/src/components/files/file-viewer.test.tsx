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
  const dialog = () => screen.getByRole("dialog").className;

  it("is nearly the window, whatever the file is", () => {
    // It used to pick between two widths by kind, and both were too narrow: a page
    // an agent laid out for a browser, a PDF, a spreadsheet and a 200-character line
    // of source all want the room, and prose does not suffer from having it.
    for (const name of ["handbook.pdf", "chart.png", "demo.mp4", "rows.csv", "report.md"]) {
      const { unmount } = open({ name });
      expect(dialog()).toContain("w-[calc(100vw-4rem)]");
      expect(dialog()).toContain("h-[calc(100vh-4rem)]");
      unmount();
    }
  });

  it("keeps a gutter rather than going edge to edge", () => {
    open({ name: "report.md" });

    // The ceilings a dialog carries by default would win over the sizes above.
    expect(dialog()).toContain("max-w-none");
    expect(dialog()).toContain("max-h-none");
  });

  it("scrolls the body rather than growing past the window", () => {
    // `min-h-0` is the whole of it: a flex child's default minimum is its content, so
    // without it a long file makes the dialog taller than the viewport instead of
    // scrolling inside it.
    const { container } = open({ name: "report.md" });
    const body = container.ownerDocument.querySelector(".flex-1.overflow-auto");

    expect(body).toHaveClass("min-h-0");
  });
});

describe("the two rows of chrome", () => {
  it("puts what kind of file it is on the name's line, not among the tabs", () => {
    // `CSV · 9 of 9` sat beside `Preview` and `Source`, cramped against them and
    // on a baseline the underlined triggers do not share - so it read as a third
    // tab that did nothing, and looked right only on the files with no tabs.
    open({ name: "runs_export.csv", size: 2048 });

    const heading = screen.getByRole("heading");
    const description = screen.getByText(/CSV/);

    expect(heading.parentElement).toBe(description.parentElement);
  });

  it("still describes the dialog exactly once", () => {
    // Radix wires `aria-describedby` to it wherever it sits; two copies is one
    // sentence a screen reader reads twice.
    open({ name: "runs_export.csv", size: 2048 });

    expect(screen.getAllByText(/CSV/)).toHaveLength(1);
  });
});

describe("paging between the files it was opened from", () => {
  /** Three files, so "the middle one" is a state both arrows can act on. */
  const NAMES = ["invoice.pdf", "notes.txt", "chart.png"];

  function withCarousel(index: number) {
    const onSelect = vi.fn();
    open({ name: NAMES[index]! }, { navigation: { names: NAMES, index, onSelect } });
    return { onSelect };
  }

  it("draws nothing for a set of one, because there is nowhere to go", () => {
    open(
      { name: "invoice.pdf" },
      { navigation: { names: ["invoice.pdf"], index: 0, onSelect: vi.fn() } },
    );

    expect(screen.queryByRole("button", { name: "Next file" })).toBeNull();
  });

  it("says where in the set this file is", () => {
    withCarousel(1);

    expect(screen.getByText(/2 of 3/)).toBeInTheDocument();
  });

  it("cannot be paged past either end", () => {
    withCarousel(0);

    expect(screen.getByRole("button", { name: "Previous file" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next file" })).toBeEnabled();
  });

  it("pages with the chevrons in both directions", async () => {
    const { onSelect } = withCarousel(1);

    await userEvent.click(screen.getByRole("button", { name: "Next file" }));
    expect(onSelect).toHaveBeenCalledWith(2);

    await userEvent.click(screen.getByRole("button", { name: "Previous file" }));
    expect(onSelect).toHaveBeenCalledWith(0);
  });

  it("names every file in the strip, not a row of dots", async () => {
    // Five attachments are five names; a dot says how many there are and nothing
    // about which one is the spreadsheet.
    const { onSelect } = withCarousel(0);

    await userEvent.click(screen.getByRole("button", { name: /chart\.png/ }));

    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("pages with the arrow keys, because a carousel is paged with them", async () => {
    const { onSelect } = withCarousel(1);

    await userEvent.keyboard("{ArrowRight}");
    expect(onSelect).toHaveBeenCalledWith(2);

    await userEvent.keyboard("{ArrowLeft}");
    expect(onSelect).toHaveBeenCalledWith(0);
  });

  it("leaves the arrow keys to the tab list, which uses them itself", async () => {
    // Radix moves between tabs with Left and Right, so paging the carousel from a
    // focused trigger remounted the viewer instead of switching the view.
    const onSelect = vi.fn();
    // A markdown file, because Preview/Source is the case where the two shortcuts
    // collide - `invoice.pdf` has one rendering and so no tab list at all.
    open(
      { name: "report.md" },
      { navigation: { names: ["report.md", "notes.txt"], index: 0, onSelect } },
    );

    screen.getByRole("tab", { name: "Source" }).focus();
    await userEvent.keyboard("{ArrowRight}");

    expect(onSelect).not.toHaveBeenCalled();
  });

  it("leaves the arrow keys alone inside a text box", async () => {
    // A source view holds one, and stealing its caret keys would be worse than
    // not having the shortcut at all.
    const { onSelect } = withCarousel(1);
    const box = document.createElement("input");
    screen.getByRole("dialog").appendChild(box);

    box.focus();
    await userEvent.keyboard("{ArrowRight}");

    expect(onSelect).not.toHaveBeenCalled();
  });
});
