import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MarkdownContent } from "./markdown-content.impl";

function markdown(content: string, onCiteClick?: (index: number) => void) {
  return render(<MarkdownContent content={content} onCiteClick={onCiteClick} />);
}

/**
 * The renderer an answer is drawn with.
 *
 * Two things here are more than styling. Citations arrive in the text as bare
 * `[3]` markers, and turning them into something clickable happens *before* the
 * Markdown is parsed - so the substitution has to leave alone the three shapes
 * that already mean something in Markdown: `[3](url)` is a link, `[3]:` is a link
 * definition, and `[text][3]` is a use of one. The third was being rewritten,
 * which turned `See [the docs][1].` into a stray bracket followed by a link.
 *
 * And the code block is where the copy button lives, because a code block is the
 * one thing in a chat answer people take away with them - which is why its text
 * is read out of the highlighter's token tree rather than assumed to be a string.
 */
describe("rendering an answer", () => {
  it("renders the usual Markdown furniture", () => {
    markdown(
      [
        "# Title",
        "## Section",
        "### Detail",
        "",
        "A paragraph with **bold** text.",
        "",
        "- first",
        "- second",
        "",
        "1. one",
        "2. two",
        "",
        "> a quotation",
        "",
        "---",
      ].join("\n"),
    );

    expect(screen.getByRole("heading", { level: 1, name: "Title" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Section" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Detail" })).toBeInTheDocument();
    expect(screen.getAllByRole("list")).toHaveLength(2);
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
    expect(screen.getByText("a quotation")).toBeInTheDocument();
    expect(screen.getByRole("separator")).toBeInTheDocument();
  });

  it("renders a GitHub-flavoured table, which is how an agent tabulates", () => {
    markdown(["| name | total |", "| --- | --- |", "| Acme | 42 |"].join("\n"));

    expect(screen.getByRole("columnheader", { name: "name" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Acme" })).toBeInTheDocument();
  });

  it("shows a fenced block's language, and offers it for copying", () => {
    // The one thing people take out of a chat answer.
    markdown("```python\nprint(1)\n```");

    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  });

  it("copies the whole block, tokens and all", async () => {
    // The highlighter replaces the code's text with a tree of spans, so reading it
    // as a string found nothing and the button was missing from every highlighted
    // block - which is nearly all of them.
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    markdown("```python\nfor i in range(3):\n    print(i)\n```");

    await userEvent.click(screen.getByRole("button", { name: /copy/i }));

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "for i in range(3):\n    print(i)\n",
    );
    vi.unstubAllGlobals();
  });

  it("offers no copy for a block with nothing in it", () => {
    // An empty fence is what a half-streamed answer looks like for a moment.
    markdown("```\n```");

    expect(screen.queryByRole("button", { name: /copy/i })).toBeNull();
  });

  it("gives a caller with its own chrome the code and nothing else", () => {
    // `run_python` pairs the code with the output it produced, in a block it heads
    // itself; a second header inside the first is chrome around chrome.
    const { container } = render(<MarkdownContent content={"```python\nprint(1)\n```"} bareCode />);

    expect(screen.queryByText("python")).toBeNull();
    expect(screen.queryByRole("button", { name: /copy/i })).toBeNull();
    expect(container.querySelector("pre")).toHaveTextContent("print(1)");
  });

  it("calls an unlabelled block text rather than leaving the header blank", () => {
    markdown("```\nsome output\n```");

    expect(screen.getByText("text")).toBeInTheDocument();
  });

  it("styles an inline code span differently from a block", () => {
    // Inline code has no language class; that absence is what tells them apart.
    markdown("Use `npm install` first.");

    expect(screen.getByText("npm install")).toHaveClass("bg-foreground/8");
  });

  it("indents a list with padding, never margin", () => {
    // An outside marker is painted left of the content box, and the turn wrapper
    // clips whatever leaves it - so a margin indent cut the numbers off.
    const { container } = markdown(["- one", "", "1. one"].join("\n"));

    const ul = container.querySelector("ul");
    const ol = container.querySelector("ol");
    expect(ul?.className).toContain("pl-5");
    expect(`${ul?.className} ${ol?.className}`).not.toMatch(/\bml-/);
  });

  it("widens an ordered list's indent to fit the widest number it draws", () => {
    // The 120-item list that found this: two digits fit 32px, three did not.
    const short = markdown(["1. one", "2. two"].join("\n"));
    expect(short.container.querySelector("ol")).toHaveClass("pl-6");
    short.unmount();

    const long = markdown(Array.from({ length: 120 }, (_, i) => `${i + 1}. item`).join("\n"));
    expect(long.container.querySelector("ol")).toHaveClass("pl-10");
    long.unmount();

    // A list that starts high is as wide as one that runs there.
    const offset = markdown(["99. ninety-nine", "100. one hundred"].join("\n"));
    expect(offset.container.querySelector("ol")).toHaveClass("pl-10");
    offset.unmount();

    const thousands = markdown("1000. item");
    expect(thousands.container.querySelector("ol")).toHaveClass("pl-12");
  });

  it("opens an external link in a new tab that cannot reach back", () => {
    markdown("See [the docs](https://docs.example/guide).");

    const link = screen.getByRole("link", { name: /the docs/ });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("leaves an in-app link in this tab", () => {
    markdown("See [settings](/settings/profile).");

    const link = screen.getByRole("link", { name: "settings" });
    expect(link).not.toHaveAttribute("target");
  });
});

describe("citations", () => {
  it("turns a bare marker into something clickable", () => {
    // The panel opens on the passage that was cited, which is only possible if
    // the marker is a control rather than text.
    const onCiteClick = vi.fn();
    markdown("Refunds run thirty days [1].", onCiteClick);

    expect(screen.getByRole("button", { name: "1" })).toHaveAttribute("title", "Source [1]");
  });

  it("hands the citation's number to the caller", async () => {
    const onCiteClick = vi.fn();
    markdown("As documented [7].", onCiteClick);

    await userEvent.click(screen.getByRole("button", { name: "7" }));

    expect(onCiteClick).toHaveBeenCalledWith(7);
  });

  it("leaves the markers as text when nothing handles them", () => {
    // Rendering an unclickable badge would be an affordance that does nothing.
    markdown("Refunds run thirty days [1].");

    expect(screen.queryByRole("button", { name: "1" })).toBeNull();
    expect(screen.getByText(/\[1\]/)).toBeInTheDocument();
  });

  it("never rewrites a real Markdown link", () => {
    // `[1](https://…)` is a link somebody wrote; turning it into a citation would
    // lose the URL.
    const onCiteClick = vi.fn();
    markdown("See [1](https://docs.example/one).", onCiteClick);

    expect(screen.getByRole("link", { name: /1/ })).toHaveAttribute(
      "href",
      "https://docs.example/one",
    );
  });

  it("never rewrites a reference-style link, or its definition", () => {
    const onCiteClick = vi.fn();
    markdown(["See [the docs][1].", "", "[1]: https://docs.example/one"].join("\n"), onCiteClick);

    expect(screen.getByRole("link", { name: /the docs/ })).toHaveAttribute(
      "href",
      "https://docs.example/one",
    );
  });

  it("marks several citations in one sentence", () => {
    const onCiteClick = vi.fn();
    markdown("Both sources agree [1][2].", onCiteClick);

    expect(screen.getByRole("button", { name: "1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2" })).toBeInTheDocument();
  });

  it("takes a three-digit citation and leaves a four-digit one alone", () => {
    // The bound is what keeps a year or an amount in square brackets from being
    // read as a source.
    const onCiteClick = vi.fn();
    markdown("Cited [123] but not [1234].", onCiteClick);

    expect(screen.getByRole("button", { name: "123" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "1234" })).toBeNull();
  });

  it("leaves a bracketed word alone", () => {
    const onCiteClick = vi.fn();
    markdown("A [note] in brackets.", onCiteClick);

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/\[note\]/)).toBeInTheDocument();
  });

  it("renders an anchor that only looks like a citation as a link", () => {
    // A `#cite-x` href nobody generated: the parse fails, so it stays a link
    // rather than becoming a badge for `NaN`.
    const onCiteClick = vi.fn();
    markdown("See [this](#cite-x).", onCiteClick);

    expect(screen.getByRole("link", { name: "this" })).toHaveAttribute("href", "#cite-x");
    expect(onCiteClick).not.toHaveBeenCalled();
  });

  it("renders a citation-shaped anchor as a link when nothing handles citations", () => {
    markdown("See [this](#cite-1).");

    expect(screen.getByRole("link", { name: "this" })).toHaveAttribute("href", "#cite-1");
  });

  it("does not cite inside a table cell by accident", () => {
    // The substitution runs over the whole document, so a marker in a cell has to
    // survive the table's own parsing.
    const onCiteClick = vi.fn();
    markdown(["| source | note |", "| --- | --- |", "| [1] | fine |"].join("\n"), onCiteClick);

    const cell = screen.getAllByRole("cell")[0]!;
    expect(within(cell).getByRole("button", { name: "1" })).toBeInTheDocument();
  });
});
