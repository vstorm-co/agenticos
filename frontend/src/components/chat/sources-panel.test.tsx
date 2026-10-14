import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SourcesPanel } from "./sources-panel";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";
import type { SourceItem } from "@/lib/chat-sources";

const bases = [{ id: "kb-1", name: "Support handbook", collection_name: "support_aa" }];
vi.mock("@/hooks/use-knowledge-bases", () => ({
  useKnowledgeBaseFor: () => (collection: string | undefined) =>
    bases.find((kb) => kb.collection_name === collection),
}));
vi.mock("./markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <p>{content}</p>,
}));
vi.mock("@/components/kb/source-viewer", () => ({
  SourceViewer: ({
    cited,
    onClose,
  }: {
    cited: { kbId: string; filename: string };
    onClose: () => void;
  }) => (
    <button type="button" onClick={onClose}>
      viewing {cited.filename} in {cited.kbId}
    </button>
  ),
}));

function rag(index: number, overrides: Partial<SourceItem> = {}): SourceItem {
  return {
    index,
    type: "rag",
    title: "handbook.pdf",
    subtitle: "p.4 · chunk 2",
    content: "Refunds are granted within thirty days.",
    score: 0.812,
    ...overrides,
  };
}

function web(index: number, overrides: Partial<SourceItem> = {}): SourceItem {
  return {
    index,
    type: "web",
    title: "Consumer rights",
    subtitle: "gov.example",
    url: "https://www.gov.example/rights",
    content: "Fourteen days.",
    ...overrides,
  };
}

function open(sources: SourceItem[], highlightedIndex: number | null = null) {
  useSourcesPanelStore.getState().open(sources, highlightedIndex);
  return render(<SourcesPanel />);
}

beforeEach(() => {
  useSourcesPanelStore.getState().close();
  useSourcesPanelStore.setState({ sources: [] });
});

/**
 * The citations panel.
 *
 * It answers one question - where did that answer come from - and the thing it
 * must not do is claim more than the tool said. A knowledge passage carries a
 * relevance score and a page; a web hit carries a link. Neither shape is rendered
 * with the other's furniture.
 *
 * The highlight is the reason the panel scrolls itself: clicking citation [7] in
 * a long answer has to land on [7], not on the top of a list of forty.
 */
describe("the sources panel", () => {
  it("renders nothing at all while it is closed", () => {
    const { container } = render(<SourcesPanel />);

    expect(container).toBeEmptyDOMElement();
  });

  it("counts what it is showing", () => {
    open([rag(1), web(2)]);

    expect(screen.getByRole("heading", { name: /Sources/ })).toHaveTextContent("(2)");
  });

  it("shows a knowledge passage with its page and its relevance", () => {
    const { container } = open([rag(1)]);

    expect(screen.getByTitle("handbook.pdf")).toBeInTheDocument();
    expect(screen.getByText("p.4 · chunk 2")).toBeInTheDocument();
    expect(screen.getByText("Refunds are granted within thirty days.")).toBeInTheDocument();
    expect(container.querySelector('[title="Relevance: 0.81"]')).toHaveClass("bg-foreground");
  });

  it("marks how relevant a passage is by band, without an alarm colour", () => {
    const { container } = open([rag(1, { score: 0.5 }), rag(2, { score: 0.1 })]);

    expect(container.querySelector('[title="Relevance: 0.50"]')).toHaveClass("bg-foreground/55");
    expect(container.querySelector('[title="Relevance: 0.10"]')).toHaveClass("bg-foreground/25");
  });

  it("shows a passage the tool did not score, without inventing one", () => {
    const { container } = open([
      rag(1, { score: undefined, subtitle: undefined, content: undefined }),
    ]);

    expect(container.querySelector('[title^="Relevance"]')).toBeNull();
    expect(screen.getByTitle("handbook.pdf")).toBeInTheDocument();
  });

  it("links a web hit to the page it came from, in a tab that cannot reach back", () => {
    open([web(1)]);

    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "https://www.gov.example/rights");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(link).getByText("gov.example")).toBeInTheDocument();
  });

  it("shows a web hit with no link as a row rather than a dead anchor", () => {
    open([web(1, { url: undefined, subtitle: undefined, content: undefined })]);

    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByTitle("Consumer rights")).toBeInTheDocument();
  });

  it("heads each group only when there is more than one kind to tell apart", () => {
    const { unmount } = open([rag(1), web(2)]);
    expect(screen.getByText("Knowledge base")).toBeInTheDocument();
    expect(screen.getByText("Web")).toBeInTheDocument();
    unmount();

    open([rag(1)]);
    expect(screen.queryByText("Knowledge base")).toBeNull();
  });

  it("shows web hits alone, with no heading over them", () => {
    open([web(1)]);

    expect(screen.queryByText("Web")).toBeNull();
    expect(screen.getByTitle("Consumer rights")).toBeInTheDocument();
  });

  it("marks the citation that was clicked, and scrolls it into view", () => {
    // Clicking [2] in a long answer has to land on [2].
    const scrollIntoView = vi.fn();
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = scrollIntoView;

    const { container } = open([rag(1), rag(2)], 2);

    const marked = container.querySelectorAll("[data-highlighted]");
    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveTextContent("2");
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "nearest" });

    Element.prototype.scrollIntoView = original;
  });

  it("scrolls a highlighted web hit into view too", () => {
    const scrollIntoView = vi.fn();
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = scrollIntoView;

    open([web(1)], 1);

    expect(scrollIntoView).toHaveBeenCalled();
    Element.prototype.scrollIntoView = original;
  });

  it("gathers a file's passages under the file, named by the base it is in", () => {
    open([
      rag(1, { collection: "support_aa" }),
      rag(2, { collection: "support_aa", content: "Duplicates are refunded at once." }),
    ]);

    // One card for the handbook, not two rows each repeating its name.
    expect(screen.getAllByTitle("handbook.pdf")).toHaveLength(1);
    expect(screen.getByText("Support handbook")).toBeInTheDocument();
    expect(screen.getByText("Duplicates are refunded at once.")).toBeInTheDocument();
  });

  it("opens the cited file whole, from the base it came from", async () => {
    open([rag(1, { collection: "support_aa" })]);

    await userEvent.click(screen.getByRole("button", { name: "Open the original" }));

    await userEvent.click(screen.getByText("viewing handbook.pdf in kb-1"));
    expect(screen.queryByText("viewing handbook.pdf in kb-1")).toBeNull();
  });

  it("folds a passage that was not cited, and opens it on request", async () => {
    open([rag(1), rag(2, { content: "Second passage." })], 1);

    // The cited one is open already, so only the other offers more.
    const more = screen.getByRole("button", { name: "Show more" });
    await userEvent.click(more);
    expect(screen.getByRole("button", { name: "Show less" })).toBeInTheDocument();
  });

  it("offers no original for a file whose base the reader cannot see", () => {
    open([rag(1, { collection: "someone_elses" })]);

    expect(screen.queryByRole("button", { name: "Open the original" })).toBeNull();
  });

  it("closes on the button", async () => {
    open([rag(1)]);

    await userEvent.click(screen.getByRole("button", { name: "Close sources panel" }));

    expect(useSourcesPanelStore.getState().isOpen).toBe(false);
  });

  it("closes on Escape, because it covers the transcript", () => {
    open([rag(1)]);

    fireEvent.keyDown(window, { key: "Escape" });

    expect(useSourcesPanelStore.getState().isOpen).toBe(false);
  });

  it("ignores every other key", () => {
    open([rag(1)]);

    fireEvent.keyDown(window, { key: "Enter" });

    expect(useSourcesPanelStore.getState().isOpen).toBe(true);
  });

  it("stops listening once it is closed", () => {
    // A panel that kept its handler would swallow Escape from whatever opened
    // after it.
    const { rerender } = open([rag(1)]);
    useSourcesPanelStore.getState().close();
    rerender(<SourcesPanel />);
    useSourcesPanelStore.setState({ isOpen: true });
    rerender(<SourcesPanel />);

    fireEvent.keyDown(window, { key: "Escape" });

    expect(useSourcesPanelStore.getState().isOpen).toBe(false);
  });
});

describe("where the panel opens", () => {
  it("covers the conversation it belongs to inside a widget, not the page's edge", () => {
    useSourcesPanelStore.getState().open([web(1)]);
    const { container } = render(<SourcesPanel contained />);

    const panel = container.firstElementChild!;
    expect(panel).toHaveClass("absolute", "inset-0");
    expect(panel).not.toHaveClass("fixed");
    // The widget's back arrow, the one its conversation list wears, closes it.
    fireEvent.click(screen.getByRole("button", { name: "Close sources panel" }));
    expect(useSourcesPanelStore.getState().isOpen).toBe(false);
  });

  it("stays at the page's right edge on the chat page", () => {
    const { container } = open([web(1)]);

    expect(container.firstElementChild).toHaveClass("fixed", "right-0");
  });
});
