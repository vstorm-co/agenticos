/** Styling shared by the prompt's reading and source views, matching CodeArea. */
export const PROMPT_VARIABLE_CLASS =
  "rounded-sm bg-violet-500/12 px-0.5 font-mono text-violet-700 dark:text-violet-300";

export function promptVariablePieces(text: string): { text: string; variable: boolean }[] {
  const pieces: { text: string; variable: boolean }[] = [];
  let at = 0;
  for (const match of text.matchAll(/\{\{\s*[a-zA-Z_][\w.]*\s*\}\}/g)) {
    if (match.index > at) pieces.push({ text: text.slice(at, match.index), variable: false });
    pieces.push({ text: match[0], variable: true });
    at = match.index + match[0].length;
  }
  if (at < text.length) pieces.push({ text: text.slice(at), variable: false });
  return pieces;
}

interface TextNode {
  type: "text";
  value: string;
}
interface ElementNode {
  type: "element";
  tagName: string;
  properties: Record<string, unknown>;
  children: Node[];
}
type Node = TextNode | ElementNode | { type: string };
interface Parent {
  children: Node[];
}
function isText(node: Node): node is TextNode {
  return node.type === "text";
}
function isElement(node: Node): node is ElementNode {
  return node.type === "element";
}
function highlight(parent: Parent): void {
  parent.children = parent.children.flatMap((child): Node[] => {
    if (isElement(child)) {
      if (!["pre", "code", "script", "style"].includes(child.tagName)) highlight(child);
      return [child];
    }
    if (!isText(child)) return [child];
    return promptVariablePieces(child.value).map((piece): Node =>
      piece.variable
        ? {
            type: "element",
            tagName: "mark",
            properties: { className: PROMPT_VARIABLE_CLASS },
            children: [{ type: "text", value: piece.text }],
          }
        : { type: "text", value: piece.text },
    );
  });
}
/** Highlight prose only; code and link destinations retain their original meaning. */
export function rehypePromptVariables() {
  return (tree: Parent) => highlight(tree);
}
