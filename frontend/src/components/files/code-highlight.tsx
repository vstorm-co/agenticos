"use client";

import { useEffect, useState, type ReactNode } from "react";
import type { createLowlight } from "lowlight";

type Highlighter = ReturnType<typeof createLowlight>;
type Tree = ReturnType<Highlighter["highlight"]>;
type Node = Tree["children"][number];

let loading: Promise<Highlighter> | null = null;

/**
 * The most text coloured, in characters. Highlighting runs on the main thread
 * in one call, and a log or a minified bundle of megabytes froze the tab for as
 * long as it took; past this the plain characters are drawn, as for a language
 * with no grammar.
 */
export const HIGHLIGHT_UP_TO = 200_000;

/**
 * The grammars, fetched once and only by a viewer that has code to colour.
 *
 * The same `common` set and the same `hljs-*` classes the chat's fenced blocks
 * get through rehype-highlight, so a file reads in the colours its code had in
 * the answer that wrote it - and the CSS for them is already there.
 */
function highlighter(): Promise<Highlighter> {
  loading ??= import("lowlight").then(({ common, createLowlight }) => createLowlight(common));
  return loading;
}

function classOf(value: unknown): string | undefined {
  return Array.isArray(value) ? value.join(" ") : undefined;
}

/** A highlighted tree as React elements; anything but a span or text draws nothing. */
export function toReact(nodes: readonly Node[]): ReactNode[] {
  return nodes.map((node, index) =>
    node.type === "element" ? (
      <span key={index} className={classOf(node.properties.className)}>
        {toReact(node.children)}
      </span>
    ) : node.type === "text" ? (
      node.value
    ) : null,
  );
}

/**
 * `text` coloured as `language`, once the grammars have loaded - and `null`
 * until then, or for a language nobody has a grammar for, so the caller draws
 * the plain characters meanwhile rather than nothing.
 */
export function useHighlighted(text: string, language: string | null): ReactNode[] | null {
  const key = `${language}\u0000${text}`;
  const [done, setDone] = useState<{ key: string; nodes: ReactNode[] } | null>(null);

  useEffect(() => {
    if (language === null || text.length > HIGHLIGHT_UP_TO) return;
    let current = true;
    void highlighter().then((lowlight) => {
      if (!current || !lowlight.registered(language)) return;
      setDone({ key, nodes: toReact(lowlight.highlight(language, text).children) });
    });
    return () => {
      current = false;
    };
  }, [key, language, text]);

  // Keyed, so a file opened after another never shows the previous one's colours.
  return done?.key === key ? done.nodes : null;
}
