"use client";

import { Download, FileDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { CopyButton } from "@/components/chat/copy-button";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { Button } from "@/components/ui";
import { codeLanguage, isRenderSafeImage, type FileKind } from "@/lib/file-kinds";
import { parseDelimited } from "@/lib/delimited";
import { cn } from "@/lib/utils";
import { useHighlighted } from "./code-highlight";

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
  /**
   * Drawn inside a pane that is already a frame - the folder page's reader - so
   * the text fills it edge to edge instead of sitting in a second box inside it.
   */
  bare?: boolean;
}

/** What a transformed kind's characters are written in, for colouring its source. */
const SOURCE_LANGUAGE: Partial<Record<FileKind, string>> = {
  markdown: "markdown",
  html: "xml",
  json: "json",
};

/**
 * A file made of characters, as whatever those characters are.
 *
 * `asSource` is checked before the kind rather than folded into it: the caller owns
 * that toggle, and a kind that has no rendered form has nothing for it to switch
 * between. Which kinds those are is `hasSourceView`, so the toggle and the render
 * cannot disagree about it.
 */
export function FileTextView({
  kind,
  name,
  text,
  asSource = false,
  bare = false,
}: FileTextViewProps) {
  const t = useTranslations("files");

  if (text.trim() === "")
    return <p className={cn("text-muted-foreground text-xs", bare && "p-4")}>{t("emptyFile")}</p>;
  if (asSource) return <PlainText text={text} language={SOURCE_LANGUAGE[kind]} bare={bare} />;

  switch (kind) {
    case "markdown":
      return bare ? (
        <div className="px-6 py-5">
          <MarkdownContent content={text} />
        </div>
      ) : (
        <MarkdownContent content={text} />
      );
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
          className={cn(
            "bg-background h-full min-h-[calc(100vh-15rem)] w-full",
            !bare && "rounded-md border",
          )}
        />
      );
    case "csv":
      return bare ? (
        <div className="p-3">
          <DelimitedTable text={text} />
        </div>
      ) : (
        <DelimitedTable text={text} />
      );
    case "json":
      return <PlainText text={prettyJson(text)} language="json" bare={bare} />;
    case "code":
      // An editor's view rather than a chat's fenced block: a fenced block is a
      // box sized to its content with a language label over it, which in a tall
      // viewer left a short file in a small box above a band of empty space.
      return <PlainText text={text} language={codeLanguage(name)} bare={bare} />;
    default:
      // `text`, and anything whose bytes turned out to be characters after all:
      // prose and pastes, read down rather than across, so wrapped.
      return <PlainText text={text} wrap bare={bare} />;
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

  if (isRenderSafeImage(mediaType))
    // A plain `img` and not `next/image`: the source is a blob URL made in this
    // browser from bytes fetched with the organization header, and the optimizer
    // would need a URL it could fetch server-side - which is exactly the request
    // that would arrive without that header.
    //
    // Gated on the render-safe allowlist, not `image/` alone: the server sends a
    // TIFF with `media_type=image/tiff` (only its disposition forced to attachment),
    // so `startsWith("image/")` would still draw a broken `<img>` for it (#1591).
    // The plain picture, not the mosaic a generated image condenses out of: the
    // effect takes its size from a box this viewer does not give it, and drew
    // nothing - a stored file is shown, not revealed.
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt={name}
        className="mx-auto max-h-[70vh] max-w-full rounded-xl object-contain"
      />
    );

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
    // In the middle of the viewer, with the file's mark over it: one line and a
    // button at the top of an empty window read as the page failing to load.
    <div className="flex h-full min-h-64 flex-col items-center justify-center gap-3 py-8 text-center">
      <span className="bg-muted text-muted-foreground flex h-14 w-14 items-center justify-center rounded-2xl">
        <FileDown className="h-6 w-6" aria-hidden />
      </span>
      <p className="text-muted-foreground max-w-md text-sm text-balance">{reason}</p>
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

/** Past this, the gutter costs more than it is worth: one element per line. */
const NUMBERED_UP_TO = 5000;

/**
 * The characters of a file, as characters.
 *
 * A bare `<pre>` of 4,000 columns of CSV is a wall: nothing says which line
 * anything is on, the block ends halfway up a tall dialog, and the only way to
 * get the text out was to select it by hand. So: a numbered gutter that stays put
 * while the code scrolls sideways, a copy button over the corner, and `h-full` so
 * the block is the height of what it is shown in.
 *
 * **The gutter is `select-none` and outside the copied text.** A reader dragging
 * across the block gets the file; numbers in the selection would make a paste
 * that has to be cleaned up by hand - which is the thing the copy button exists
 * to avoid.
 *
 * Source and JSON are not wrapped: a line of code is read across, and a
 * record is a record. Plain text - prose, a paste - is (`wrap`): one 2,000
 * character line ran off the side of the viewer as a single unreadable row.
 * Wrapped, each line is its own row with its number beside it, so a number
 * stays with the line it counts however many rows the line takes.
 */
function PlainText({
  text,
  wrap = false,
  language,
  bare,
}: {
  text: string;
  wrap?: boolean;
  /** The grammar the characters are coloured with; absent or `text` for none. */
  language?: string;
  bare: boolean;
}) {
  const lines = text.split("\n");
  const numbered = lines.length <= NUMBERED_UP_TO;
  const coloured = useHighlighted(text, wrap || language === "text" ? null : (language ?? null));
  const frame = cn(
    "relative h-full min-h-64 overflow-hidden",
    bare ? "bg-muted/20" : "bg-muted/30 rounded-md border",
  );

  if (wrap) {
    return (
      <div className={frame}>
        <CopyButton text={text} className="absolute top-1 right-1 z-10" />
        <div className="h-full overflow-auto py-3 pr-10 font-mono text-xs leading-[1.6]">
          {numbered ? (
            <div className="grid grid-cols-[auto_minmax(0,1fr)]">
              {lines.map((line, index) => (
                <div key={index} className="contents">
                  <span
                    aria-hidden
                    className="text-muted-foreground px-3 text-right tabular-nums select-none"
                  >
                    {index + 1}
                  </span>
                  <span className="text-foreground/90 break-all whitespace-pre-wrap">
                    {line === "" ? "\u00a0" : line}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <pre className="text-foreground/90 px-3 break-all whitespace-pre-wrap">{text}</pre>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={frame}>
      <CopyButton text={text} className="absolute top-2 right-2 z-10" />

      <div className="h-full overflow-auto">
        <div className="flex min-h-full min-w-max font-mono text-[12.5px] leading-[1.7]">
          {numbered && (
            // Its own fill, so the code scrolling sideways passes under it rather
            // than showing through the numbers.
            <pre
              aria-hidden
              className="text-muted-foreground/70 bg-muted/60 border-border/60 sticky left-0 min-w-12 shrink-0 border-r py-4 pr-3 pl-4 text-right tabular-nums select-none"
            >
              {lines.map((_, index) => index + 1).join("\n")}
            </pre>
          )}
          <pre className="hljs text-foreground/90 flex-1 py-4 pr-12 pl-4 whitespace-pre">
            {coloured ?? text}
          </pre>
        </div>
      </div>
    </div>
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
                  className="border-border border-b px-2.5 py-1.5 text-left font-mono text-xs font-semibold tracking-wider uppercase"
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
        <p className="text-muted-foreground text-center text-xs tracking-wider uppercase">
          {t("truncatedRows", { shown: MAX_ROWS, total: body.length })}
        </p>
      )}
    </div>
  );
}
