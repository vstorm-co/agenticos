"use client";

import { Download } from "lucide-react";
import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { Button } from "@/components/ui";
import { codeLanguage, type FileKind } from "@/lib/file-kinds";
import { parseDelimited } from "@/lib/delimited";

/**
 * One file's content on screen, once something has fetched it.
 *
 * Nothing here fetches, and that is the whole point of the split: a skill's file is
 * already in memory as a draft somebody is editing, a workspace file arrives from a
 * query, and a knowledge base document from a third route. They render identically
 * because rendering is what these are, and only these.
 */

interface FileTextViewProps {
  kind: FileKind;
  /** Used for the language a code file is fenced with, and to title a frame. */
  name: string;
  text: string;
  /** Show the characters rather than the document they make, where those differ. */
  asSource?: boolean;
}

/**
 * A file made of characters, as whatever those characters are.
 *
 * `asSource` is checked before the kind rather than folded into it: the caller owns
 * that toggle, and a kind that has no rendered form has nothing for it to switch
 * between. Which kinds those are is `hasSourceView`, so the toggle and the render
 * cannot disagree about it.
 */
export function FileTextView({ kind, name, text, asSource = false }: FileTextViewProps) {
  const t = useTranslations("files");

  if (text.trim() === "") return <p className="text-muted-foreground text-xs">{t("emptyFile")}</p>;
  if (asSource) return <PlainText text={text} />;

  switch (kind) {
    case "markdown":
      return <MarkdownContent content={text} />;
    case "html":
      // Sandboxed with no allowances, which is what makes showing this safe at all:
      // the API refuses to serve HTML inline because a document an agent wrote and
      // served from this origin is stored XSS. Rendered from `srcDoc` into an opaque
      // origin it can reach nothing - no script, no form, no cookie, no DOM.
      return (
        <iframe
          title={t("renderedPage", { name })}
          srcDoc={text}
          sandbox=""
          // `h-full` with a viewport-relative floor, for the reason the PDF below
          // carries: nothing between here and the viewer's body adds a wrapper, so
          // the height resolves - and where it cannot, the floor still draws a page.
          className="bg-background h-full min-h-[calc(100vh-15rem)] w-full rounded-md border"
        />
      );
    case "csv":
      return <DelimitedTable text={text} />;
    case "json":
      return <PlainText text={prettyJson(text)} />;
    case "code":
      // The Markdown renderer highlights fenced code, so a source file is fenced
      // with its own language rather than this growing a second highlighter.
      return <MarkdownContent content={`\`\`\`${codeLanguage(name)}\n${text}\n\`\`\``} />;
    default:
      // `text`, and anything whose bytes turned out to be characters after all.
      return <PlainText text={text} />;
  }
}

interface FileBytesViewProps {
  name: string;
  url: string;
  /**
   * What the server said these bytes are.
   *
   * The branch is on this and never on the name, because what may be *displayed* is
   * the API's decision: a short allowlist of raster images plus PDF, and everything
   * else typed `application/octet-stream` precisely so a browser cannot decide a
   * body is HTML after all. A second list of suffixes here would be a second answer
   * that drifts the first time either moves.
   */
  mediaType: string;
  onDownload: () => void;
}

/** A file made of bytes, as whatever the server agreed to call it. */
export function FileBytesView({ name, url, mediaType, onDownload }: FileBytesViewProps) {
  const t = useTranslations("files");

  if (mediaType.startsWith("image/"))
    // A plain `img` and not `next/image`: the source is a blob URL made in this
    // browser from bytes fetched with the organization header, and the optimizer
    // would need a URL it could fetch server-side - which is exactly the request
    // that would arrive without that header.
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={url} alt={name} className="max-h-[70vh] w-full object-contain" />;

  if (mediaType === "application/pdf")
    // An iframe rather than an object or an embed: it is the element every browser
    // routes to its own PDF viewer, and that viewer renders the document without
    // handing it this page's DOM.
    // `h-full` first and the viewport fraction as a floor: in the viewer the body
    // is a flex child with a definite height, so `h-full` fills it exactly and a
    // fixed 70vh left a band of empty dialog under a 119-page document. Where
    // nothing above has a height - a panel that grows to its content - `h-full`
    // computes to `auto` and the floor is what draws the page.
    return (
      <iframe src={url} title={name} className="h-full min-h-[70vh] w-full rounded-md border-0" />
    );

  if (mediaType.startsWith("video/"))
    return (
      // No caption track, and there is none to offer: this is a file somebody's agent
      // produced or uploaded, with no transcript beside it to point at. An empty
      // `<track>` would satisfy the rule and tell a screen reader nothing.
      // eslint-disable-next-line jsx-a11y/media-has-caption
      <video src={url} controls title={name} className="max-h-[70vh] w-full rounded-md bg-black" />
    );

  // eslint-disable-next-line jsx-a11y/media-has-caption -- as above: no transcript exists
  if (mediaType.startsWith("audio/")) return <audio src={url} controls className="w-full" />;

  // The server did not serve it as something displayable, whatever the name
  // suggested. A broken `<img>` with nothing saying why is the worst of the three
  // answers; the download is the one that works.
  return <FileUnavailable reason={t("servedAsFile")} onDownload={onDownload} />;
}

/** Why this file is not on screen, with the way to read it anyway. */
export function FileUnavailable({
  reason,
  onDownload,
  error = null,
}: {
  reason: string;
  onDownload: () => void;
  /** Why the offer below failed, when it has been taken and did. */
  error?: string | null;
}) {
  const t = useTranslations("files");

  return (
    <div className="space-y-2 py-4 text-center">
      <p className="text-muted-foreground text-sm">{reason}</p>
      <Button variant="outline" size="sm" onClick={onDownload}>
        <Download className="h-3.5 w-3.5" />
        {t("download")}
      </Button>
      {/* A container-backed host refuses a binary either way, so the offer above can
          fail too - and silently, before this. */}
      {error !== null && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}

/**
 * The characters, as they are.
 *
 * `whitespace-pre` and a scroll rather than `pre-wrap`: source read as source is
 * read by its indentation, and wrapping a 200-character line into four rows at the
 * left margin destroys exactly the thing somebody switched to this view for. Prose
 * in a `.txt` loses nothing by scrolling, and gains not being reflowed.
 */
function PlainText({ text }: { text: string }) {
  return (
    <pre className="bg-muted text-foreground/90 overflow-x-auto rounded-md p-3 font-mono text-xs whitespace-pre">
      {text}
    </pre>
  );
}

/** Indented when it parses, and as it stands when it does not - which is the answer. */
function prettyJson(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

const MAX_ROWS = 500;

/**
 * A delimited file as the table it is.
 *
 * Bounded at five hundred rows and *saying* so: a hundred thousand rows in the DOM
 * is a dialog that never opens, and a table silently missing its tail is a table
 * that lies about the file.
 */
function DelimitedTable({ text }: { text: string }) {
  const t = useTranslations("files");
  // At least one row, always: the caller returns early on a blank file and every
  // other input ends a row, which `parseDelimited`'s own tests pin. The `?? []` is
  // the narrowing that fact needs, not a case anything reaches.
  const [first, ...body] = parseDelimited(text);
  const header = first ?? [];
  const visible = body.slice(0, MAX_ROWS);

  return (
    <div className="space-y-2">
      <div className="border-border overflow-x-auto rounded-md border">
        <table className="min-w-full text-xs">
          <thead className="bg-muted sticky top-0">
            <tr>
              {header.map((cell, index) => (
                <th
                  key={index}
                  className="border-border border-b px-2.5 py-1.5 text-left font-mono text-[10px] font-semibold tracking-wider uppercase"
                >
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, rowIndex) => (
              <tr key={rowIndex} className="hover:bg-accent/40">
                {row.map((cell, cellIndex) => (
                  <td
                    key={cellIndex}
                    className="border-border border-b px-2.5 py-1.5 align-top whitespace-nowrap"
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {body.length > MAX_ROWS && (
        <p className="text-muted-foreground text-center text-[10px] tracking-wider uppercase">
          {t("truncatedRows", { shown: MAX_ROWS, total: body.length })}
        </p>
      )}
    </div>
  );
}
