/** The selected words become part of a reply's persisted context. */
export const MAX_SELECTED_QUOTE_CODEPOINTS = 280;

export interface SelectedMessageQuote {
  kind: "quote";
  text: string;
  /** The saved row that supplied the selected prose, absent on older ordinary rows. */
  sourceMessageId?: string;
}

export interface UnquotableMessageSelection {
  kind: "unquotable";
}

/**
 * Read a selection only when it starts and ends inside one marked message block.
 *
 * Tool controls, citations and other interactive content are never quote sources.
 * `Range.toString()` returns rendered text across Markdown nodes, so a quote does
 * not copy the message's Markdown syntax into the composer.
 */
export function selectedMessageQuote(
  selection: Selection | null,
  messageElement: HTMLElement | null,
): SelectedMessageQuote | UnquotableMessageSelection | null {
  if (!selection || !messageElement || selection.isCollapsed || selection.rangeCount !== 1) {
    return null;
  }

  const range = selection.getRangeAt(0);
  const quoteable = Array.from(
    messageElement.querySelectorAll<HTMLElement>("[data-quoteable-content]"),
  ).find(
    (element) => element.contains(range.startContainer) && element.contains(range.endContainer),
  );
  if (!quoteable) return null;

  // A present empty marker is deliberate: the part came from an unsaved source
  // row, so it cannot be quoted against the visible coalesced row's id.
  const sourceMessageId = quoteable.getAttribute("data-quote-source-message-id");
  if (sourceMessageId === "") return { kind: "unquotable" };

  const excluded = quoteable.querySelectorAll<HTMLElement>(
    'button, [role="button"], input, select, textarea, [contenteditable="true"], [data-quote-exclude]',
  );
  if (Array.from(excluded).some((element) => range.intersectsNode(element))) return null;

  const normalized = range
    .toString()
    .replace(/\u00a0/g, " ")
    .split(/\s+/u)
    .filter(Boolean)
    .join(" ");
  if (!normalized) return null;

  return {
    kind: "quote",
    text: Array.from(normalized).slice(0, MAX_SELECTED_QUOTE_CODEPOINTS).join(""),
    ...(sourceMessageId ? { sourceMessageId } : {}),
  };
}
