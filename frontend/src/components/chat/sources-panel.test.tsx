import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SourcesPanel } from "./sources-panel";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";
import type { SourceItem } from "@/lib/chat-sources";

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

    const rows = container.querySelectorAll(".rounded-xl.border");
    expect(rows[1]).toHaveClass("bg-foreground/[0.04]");
    expect(rows[0]).not.toHaveClass("bg-foreground/[0.04]");
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
