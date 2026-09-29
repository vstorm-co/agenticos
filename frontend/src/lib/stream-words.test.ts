import { describe, expect, it } from "vitest";

import { rehypeStreamWords, STREAM_WORD_CLASS } from "./stream-words";

type Node = { type: string; tagName?: string; value?: string; children?: Node[] };

function text(value: string): Node {
  return { type: "text", value };
}

function el(tagName: string, children: Node[]): Node {
  return { type: "element", tagName, properties: {}, children } as Node;
}

/** Run the plugin over a root holding `children`, and hand the root back. */
function run(...children: Node[]): Node {
  const root = { type: "root", children };
  rehypeStreamWords()(root as Parameters<ReturnType<typeof rehypeStreamWords>>[0]);
  return root;
}

/** The node at `path` under `node`, failing the test rather than reading `undefined`. */
function at(node: Node, ...path: number[]): Node {
  return path.reduce((current, index) => {
    const next = current.children?.[index];
    if (next === undefined) throw new Error(`no child ${index}`);
    return next;
  }, node);
}

/** Each child as `[word]` for a word span, `<tag>` for other markup, or its text. */
function words(node: Node): string[] {
  return (node.children ?? []).map((child) => {
    if (child.type !== "element") return `${child.value}`;
    return child.tagName === "span" ? `[${at(child, 0).value}]` : `<${child.tagName}>`;
  });
}

describe("rehypeStreamWords", () => {
  it("gives each word, with the space after it, a span of its own", () => {
    const root = run(el("p", [text("Hello there, world")]));

    expect(words(at(root, 0))).toEqual(["[Hello ]", "[there, ]", "[world]"]);
    expect(at(root, 0, 0)).toMatchObject({
      tagName: "span",
      properties: { className: [STREAM_WORD_CLASS] },
    });
  });

  it("reaches words inside inline markup", () => {
    const root = run(el("p", [el("strong", [text("very bold")])]));

    expect(words(at(root, 0, 0))).toEqual(["[very ]", "[bold]"]);
  });

  it("keeps leading whitespace as plain text", () => {
    const root = run(el("p", [el("em", [text("a")]), text(" then")]));

    expect(words(at(root, 0))).toEqual(["<em>", " ", "[then]"]);
  });

  it("leaves whitespace between blocks alone", () => {
    const root = run(el("ul", [text("\n"), el("li", [text("one")]), text("\n")]));

    expect(words(at(root, 0))).toEqual(["\n", "<li>", "\n"]);
  });

  it("leaves code untouched", () => {
    const root = run(
      el("pre", [el("code", [text("const answer = 42;")])]),
      el("p", [el("code", [text("inline code")])]),
    );

    expect(at(root, 0, 0).children).toEqual([text("const answer = 42;")]);
    expect(at(root, 1, 0).children).toEqual([text("inline code")]);
  });

  it("passes other node kinds through", () => {
    const comment = { type: "comment", value: "note" };

    expect(run(comment).children).toEqual([comment]);
  });
});
