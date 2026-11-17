import { describe, expect, it } from "vitest";

import { MAX_SELECTED_QUOTE_CODEPOINTS, selectedMessageQuote } from "./selected-message-quote";

function select(root: HTMLElement, start: Node, startOffset: number, end: Node, endOffset: number) {
  if (!root.isConnected) document.body.append(root);
  const range = document.createRange();
  range.setStart(start, startOffset);
  range.setEnd(end, endOffset);
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
  return selection;
}

describe("selectedMessageQuote", () => {
  it("rejects absent, collapsed and rangeless selections", () => {
    const message = document.createElement("div");
    const text = document.createTextNode("A saved answer.");
    message.append(text);

    expect(selectedMessageQuote(null, message)).toBeNull();

    const selection = select(message, text, 0, text, 4);
    expect(selectedMessageQuote(selection, null)).toBeNull();

    selection.collapseToStart();
    expect(selectedMessageQuote(selection, message)).toBeNull();

    expect(
      selectedMessageQuote({ isCollapsed: false, rangeCount: 0 } as Selection, message),
    ).toBeNull();
  });

  it("returns rendered text with whitespace folded across inline Markdown nodes", () => {
    const message = document.createElement("div");
    message.innerHTML =
      "<div data-quoteable-content>Keep <strong>the original</strong> text.</div>";
    const quoteable = message.querySelector("[data-quoteable-content]")!;
    const first = quoteable.firstChild!;
    const emphasized = quoteable.querySelector("strong")!.firstChild!;
    const selection = select(message, first, 5, emphasized, 12);

    expect(selection.isCollapsed).toBe(false);
    expect(selection.rangeCount).toBe(1);
    expect(selection.toString()).toBe("the original");
    expect(quoteable.contains(selection.getRangeAt(0).startContainer)).toBe(true);
    expect(quoteable.contains(selection.getRangeAt(0).endContainer)).toBe(true);
    expect(selectedMessageQuote(selection, message)).toEqual({
      kind: "quote",
      text: "the original",
    });
  });

  it("returns the saved source row for a quoteable part", () => {
    const message = document.createElement("div");
    message.innerHTML =
      '<p data-quoteable-content data-quote-source-message-id="saved-earlier">Earlier words.</p>';
    const text = message.querySelector("p")!.firstChild!;
    const selection = select(message, text, 0, text, 13);

    expect(selectedMessageQuote(selection, message)).toEqual({
      kind: "quote",
      text: "Earlier words",
      sourceMessageId: "saved-earlier",
    });
  });

  it("marks an unsaved source as unquotable instead of returning a fallback row", () => {
    const message = document.createElement("div");
    message.innerHTML =
      '<p data-quoteable-content data-quote-source-message-id="">Unsaved words.</p>';
    const text = message.querySelector("p")!.firstChild!;
    const selection = select(message, text, 0, text, 13);

    expect(selectedMessageQuote(selection, message)).toEqual({ kind: "unquotable" });
  });

  it("rejects a selection that normalizes to no visible words", () => {
    const message = document.createElement("div");
    message.innerHTML = "<p data-quoteable-content>   </p>";
    const text = message.querySelector("p")!.firstChild!;
    const selection = select(message, text, 0, text, 3);

    expect(selectedMessageQuote(selection, message)).toBeNull();
  });

  it("rejects a selection that spans separate prose blocks", () => {
    const message = document.createElement("div");
    message.innerHTML =
      "<p data-quoteable-content>First block.</p><p data-quoteable-content>Second block.</p>";
    const blocks = message.querySelectorAll("[data-quoteable-content]");
    const selection = select(message, blocks[0]!.firstChild!, 0, blocks[1]!.firstChild!, 6);

    expect(selectedMessageQuote(selection, message)).toBeNull();
  });

  it("rejects a selection that reaches an adjacent message", () => {
    const transcript = document.createElement("div");
    transcript.innerHTML =
      '<article data-message-id="one"><p data-quoteable-content>One.</p></article>' +
      '<article data-message-id="two"><p data-quoteable-content>Two.</p></article>';
    const messages = transcript.querySelectorAll<HTMLElement>("[data-message-id]");
    const one = messages[0]!.querySelector("[data-quoteable-content]")!.firstChild!;
    const two = messages[1]!.querySelector("[data-quoteable-content]")!.firstChild!;
    const selection = select(transcript, one, 0, two, 3);

    expect(selectedMessageQuote(selection, messages[0]!)).toBeNull();
  });

  it("rejects a selection that includes a tool or citation control", () => {
    const message = document.createElement("div");
    message.innerHTML =
      '<div data-quoteable-content>Read <button type="button">source</button> carefully.</div>';
    const quoteable = message.querySelector("[data-quoteable-content]")!;
    const leading = quoteable.firstChild!;
    const controlText = quoteable.querySelector("button")!.firstChild!;
    const selection = select(message, leading, 0, controlText, 6);

    expect(selectedMessageQuote(selection, message)).toBeNull();
  });

  it("normalizes rendered whitespace and limits the quote by Unicode code points", () => {
    const message = document.createElement("div");
    const quoteable = document.createElement("p");
    quoteable.dataset.quoteableContent = "";
    quoteable.textContent = `  café\u00a0${"🙂".repeat(MAX_SELECTED_QUOTE_CODEPOINTS)}  `;
    message.append(quoteable);
    const text = quoteable.firstChild!;
    const selection = select(message, text, 0, text, text.textContent!.length);

    const quote = selectedMessageQuote(selection, message)!;
    expect(quote.kind).toBe("quote");
    if (quote.kind !== "quote") throw new Error("expected a quote");
    expect(quote.text.startsWith("café ")).toBe(true);
    expect(Array.from(quote.text)).toHaveLength(MAX_SELECTED_QUOTE_CODEPOINTS);
  });
});
