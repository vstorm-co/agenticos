/**
 * A rehype plugin that wraps every word of a streaming answer in its own span,
 * so each one can fade in as it arrives instead of the paragraph growing a
 * hard edge.
 *
 * React reconciles the rendered tree by position, so the spans already on the
 * page keep their DOM nodes from one render to the next and only the words
 * appended at the end mount - which is what plays their animation once, and
 * never again for a word already read. Code is left alone: its highlighter
 * already splits it into spans, and a fading token inside a code block reads
 * as flicker rather than flow.
 */

interface HastText {
  type: "text";
  value: string;
}

interface HastElement {
  type: "element";
  tagName: string;
  properties: Record<string, unknown>;
  children: HastNode[];
}

type HastNode = HastText | HastElement | { type: string };

interface HastParent {
  children: HastNode[];
}

/** A word and the whitespace after it, or a run of whitespace nothing precedes. */
const TOKEN = /\S+\s*|\s+/g;

/** Subtrees whose text is not prose. */
const UNTOUCHED = new Set(["pre", "code", "script", "style"]);

export const STREAM_WORD_CLASS = "stream-word";

function isText(node: HastNode): node is HastText {
  return node.type === "text";
}

function isElement(node: HastNode): node is HastElement {
  return node.type === "element";
}

function wordSpan(value: string): HastElement {
  return {
    type: "element",
    tagName: "span",
    properties: { className: [STREAM_WORD_CLASS] },
    children: [{ type: "text", value }],
  };
}

function split(parent: HastParent): void {
  parent.children = parent.children.flatMap((child): HastNode[] => {
    if (isElement(child)) {
      if (!UNTOUCHED.has(child.tagName)) split(child);
      return [child];
    }
    // Whitespace between blocks - between table rows, list items - stays a
    // bare text node: a span there is invalid markup and shifts the layout.
    if (!isText(child) || child.value.trim() === "") return [child];
    return Array.from(child.value.matchAll(TOKEN), ([token]) =>
      token.trim() === "" ? { type: "text", value: token } : wordSpan(token),
    );
  });
}

export function rehypeStreamWords() {
  return (tree: HastParent) => split(tree);
}
