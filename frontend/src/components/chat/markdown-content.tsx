"use client";

import dynamic from "next/dynamic";

export interface MarkdownContentProps {
  content: string;
  onCiteClick?: (index: number) => void;
  /**
   * Render a fenced block as its `<pre>` alone - no box, no header, no copy button.
   *
   * For a caller that has already drawn chrome around the block and would otherwise
   * get a second one inside it: `run_python`, whose code sits in a collapsible block
   * paired with the output it produced. An answer's own code blocks never pass it.
   */
  bareCode?: boolean;
}

/**
 * Public markdown renderer. The heavy markdown stack (react-markdown +
 * remark-gfm + rehype-highlight) is split into `markdown-content.impl.tsx` and
 * loaded on demand via `next/dynamic`, keeping it out of the initial bundle of
 * pages that never render chat markdown. The prop API is unchanged, so callers
 * (message rendering, file preview) need no changes.
 *
 * `ssr: false` is safe here - chat content is client-rendered and streamed in.
 * The fallback mirrors the streamed text so progressive rendering still shows
 * content immediately while the renderer chunk loads, then swaps to the rich
 * markdown output once ready.
 */
const MarkdownContentImpl = dynamic(
  () => import("./markdown-content.impl").then((m) => m.MarkdownContent),
  {
    ssr: false,
    loading: () => <p className="text-foreground/55 leading-relaxed whitespace-pre-wrap">&nbsp;</p>,
  },
);

export function MarkdownContent({ content, onCiteClick, bareCode }: MarkdownContentProps) {
  return <MarkdownContentImpl content={content} onCiteClick={onCiteClick} bareCode={bareCode} />;
}
