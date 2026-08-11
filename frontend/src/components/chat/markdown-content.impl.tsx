"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";

import { CollapsibleBlock } from "./collapsible-block";
import type { MarkdownContentProps } from "./markdown-content";

/** Parse `language-xyz` from a `<code>` className that rehype-highlight emits. */
function languageLabel(className: string | undefined): string | null {
  if (!className) return null;
  const match = /(?:^|\s)language-([a-z0-9+\-]+)/i.exec(className);
  return match && match[1] ? match[1].toLowerCase() : null;
}

/**
 * Pre-process markdown to turn bare citation markers [N] into markdown links
 * with a special `#cite-N` href. The `a` component override below detects this
 * and renders an interactive CitationBadge instead of a regular link.
 *
 * Three shapes are left alone, because in Markdown they already mean something
 * and rewriting them corrupts the answer:
 *
 *   - `[N](url)` is a link somebody wrote - the lookahead for `(`.
 *   - `[N]: url` is a link reference definition - the lookahead for `:`.
 *   - `[text][N]` is a *use* of one, and this is the one that was broken:
 *     rewriting its label turned `See [the docs][1].` into `See [the docs][`
 *     followed by a stray link. The first alternative matches that whole form
 *     and hands it back untouched.
 *
 * The label check is `(?!\d{1,3}\])` so that consecutive citations - `[1][2]`,
 * which an agent writes when two sources agree - are still both marked.
 *
 * Code spans and blocks are left as-is because the regex does not enter them; in
 * practice agent responses never cite inside code.
 */
const CITATION = /(\[(?!\d{1,3}\])[^\]]*\]\[\d{1,3}\])|\[(\d{1,3})\](?![\(:])/g;

function preprocessCitations(content: string): string {
  return content.replace(CITATION, (_, referenceLink: string | undefined, n: string) =>
    referenceLink === undefined ? `[[${n}]](#cite-${n})` : referenceLink,
  );
}

/**
 * The text of a fenced block, whatever shape the highlighter left it in.
 *
 * `rehype-highlight` replaces the code's single text child with a tree of
 * `<span>` tokens, so reading `children` as a string found one only for a block
 * whose language nothing recognised - which is why the copy button, the single
 * most-used control on a code block, was missing from every highlighted one.
 */
function textOf(node: React.ReactNode): string {
  if (typeof node === "string") return node;
  /* v8 ignore next -- react-markdown hands children through as strings */
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && typeof node === "object" && "props" in node) {
    return textOf((node as React.ReactElement<{ children?: React.ReactNode }>).props.children);
  }
  return "";
}

export function MarkdownContent({ content, onCiteClick, bareCode }: MarkdownContentProps) {
  const t = useTranslations("chat");
  const processed = onCiteClick ? preprocessCitations(content) : content;
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={{
        pre({ children, ...props }) {
          const block = (
            <pre className="overflow-x-auto p-3.5 text-[12.5px] leading-relaxed" {...props}>
              {children}
            </pre>
          );
          if (bareCode) return block;

          const codeElement = children as React.ReactElement<{
            children?: React.ReactNode;
            className?: string;
          }>;
          const codeContent = textOf(codeElement?.props?.children);
          const lang = languageLabel(codeElement?.props?.className);

          return (
            <CollapsibleBlock
              className="my-3"
              // An unlabelled block is still called something, unless it is also
              // empty - which is what a half-streamed answer looks like for a moment,
              // and a bar reading "text" over nothing is chrome around nothing.
              label={lang ?? (codeContent === "" ? null : "text")}
              copyText={codeContent}
            >
              {block}
            </CollapsibleBlock>
          );
        },
        code({ className, children, ...props }) {
          const isInline = !className;
          if (isInline) {
            return (
              <code
                className="bg-foreground/8 text-foreground rounded px-1.5 py-0.5 font-mono text-[0.85em]"
                {...props}
              >
                {children}
              </code>
            );
          }
          return (
            <code className={className} {...props}>
              {children}
            </code>
          );
        },
        a({ href, children, ...props }) {
          if (href?.startsWith("#cite-") && onCiteClick) {
            const n = parseInt(href.slice(6), 10);
            if (!Number.isNaN(n)) {
              return (
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    onCiteClick(n);
                  }}
                  className="bg-foreground/10 text-foreground/70 hover:bg-foreground/20 mx-0.5 inline-flex h-[1.1em] cursor-pointer items-center rounded px-1 align-middle font-mono text-[0.72em] font-semibold tabular-nums transition-colors"
                  title={t("sourceNumber", { marker: `[${n}]` })}
                >
                  {n}
                </button>
              );
            }
          }
          const isExternal = !!href && /^https?:\/\//i.test(href);
          return (
            <a
              href={href}
              target={isExternal ? "_blank" : undefined}
              rel={isExternal ? "noopener noreferrer" : undefined}
              className="text-foreground hover:text-brand-hover decoration-brand hover:decoration-brand inline-flex items-baseline gap-0.5 font-medium underline decoration-2 underline-offset-[3px] transition-colors"
              {...props}
            >
              {children}
              {isExternal && (
                <ExternalLink className="text-foreground/60 inline h-[0.8em] w-[0.8em] shrink-0 -translate-y-[1px]" />
              )}
            </a>
          );
        },
        p({ children, ...props }) {
          return (
            <p className="mb-3 leading-relaxed last:mb-0" {...props}>
              {children}
            </p>
          );
        },
        ul({ children, ...props }) {
          return (
            <ul
              className="marker:text-foreground/40 mb-3 ml-5 list-disc space-y-1 last:mb-0"
              {...props}
            >
              {children}
            </ul>
          );
        },
        ol({ children, ...props }) {
          return (
            <ol
              className="marker:text-foreground/40 mb-3 ml-5 list-decimal space-y-1 last:mb-0"
              {...props}
            >
              {children}
            </ol>
          );
        },
        li({ children, ...props }) {
          return (
            <li className="leading-relaxed" {...props}>
              {children}
            </li>
          );
        },
        h1({ children, ...props }) {
          return (
            <h1 className="mt-4 mb-2 text-xl font-bold tracking-tight first:mt-0" {...props}>
              {children}
            </h1>
          );
        },
        h2({ children, ...props }) {
          return (
            <h2 className="mt-4 mb-2 text-lg font-semibold tracking-tight first:mt-0" {...props}>
              {children}
            </h2>
          );
        },
        h3({ children, ...props }) {
          return (
            <h3 className="mt-3 mb-2 text-base font-semibold first:mt-0" {...props}>
              {children}
            </h3>
          );
        },
        blockquote({ children, ...props }) {
          return (
            <blockquote
              className="border-brand/40 text-foreground/75 my-3 border-l-2 pl-4 italic"
              {...props}
            >
              {children}
            </blockquote>
          );
        },
        table({ children, ...props }) {
          return (
            <div className="border-foreground/10 my-3 overflow-x-auto rounded-lg border">
              <table className="min-w-full text-sm" {...props}>
                {children}
              </table>
            </div>
          );
        },
        thead({ children, ...props }) {
          return (
            <thead className="bg-foreground/[0.04]" {...props}>
              {children}
            </thead>
          );
        },
        th({ children, ...props }) {
          return (
            <th
              className="border-foreground/10 border-b px-3 py-2 text-left font-mono text-[11px] font-semibold tracking-wider uppercase"
              {...props}
            >
              {children}
            </th>
          );
        },
        td({ children, ...props }) {
          return (
            <td className="border-foreground/8 border-b px-3 py-2 last:border-0" {...props}>
              {children}
            </td>
          );
        },
        hr({ ...props }) {
          return <hr className="border-foreground/10 my-4" {...props} />;
        },
      }}
    >
      {processed}
    </ReactMarkdown>
  );
}
