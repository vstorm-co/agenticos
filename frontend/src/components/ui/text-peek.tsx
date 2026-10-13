import { cn } from "@/lib/utils";

type PeekLine =
  | { kind: "heading"; level: number; text: string }
  | { kind: "item"; marker: string; text: string }
  | { kind: "text"; text: string }
  | { kind: "gap" };

/** Inline markdown a thumbnail has no room to style: links, emphasis, code ticks. */
function plain(text: string): string {
  return text
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/(\*\*|__)(.+?)\1/g, "$2")
    .replace(/(\*|_)(.+?)\1/g, "$2")
    .replace(/`([^`]*)`/g, "$1")
    .trim();
}

/**
 * The opening of a markdown body, read as the shapes a thumbnail can draw.
 *
 * Deliberately not a markdown renderer: a card shows eight lines at 11px, where a
 * table or a code block is noise, and a grid of thirty cards is thirty renders.
 * A heading, a list item and a paragraph are the three things legible at this
 * size; fences are dropped and runs of blank lines collapse to one gap. Lines
 * of one paragraph are joined, because a body hard-wrapped at 72 columns would
 * otherwise read as a stack of truncated fragments.
 */
export function peekLines(source: string): PeekLine[] {
  const lines: PeekLine[] = [];
  for (const raw of source.split("\n")) {
    const line = raw.trim();
    if (line.startsWith("```")) continue;
    if (line === "") {
      if (lines.length > 0 && lines[lines.length - 1]!.kind !== "gap") lines.push({ kind: "gap" });
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      lines.push({ kind: "heading", level: heading[1]!.length, text: plain(heading[2]!) });
      continue;
    }
    const item = /^([-*+]|\d+[.)])\s+(.*)$/.exec(line);
    if (item) {
      const marker = /^\d/.test(item[1]!) ? item[1]! : "•";
      lines.push({ kind: "item", marker, text: plain(item[2]!) });
      continue;
    }
    const previous = lines[lines.length - 1];
    if (previous?.kind === "text") previous.text = `${previous.text} ${plain(line)}`;
    else lines.push({ kind: "text", text: plain(line) });
  }
  return lines;
}

/**
 * A page with nothing written on it yet - faint rules where the lines would be,
 * rather than the card's description repeated on the paper above it.
 */
export function BlankPeek() {
  return (
    <div aria-hidden className="space-y-2 pt-1">
      <div className="bg-muted h-2.5 w-2/5 rounded" />
      <div className="bg-muted/70 h-2 w-4/5 rounded" />
      <div className="bg-muted/70 h-2 w-3/5 rounded" />
      <div className="bg-muted/70 h-2 w-2/3 rounded" />
    </div>
  );
}

interface TextPeekProps {
  source: string;
  /** `markdown` reads headings and lists; `plain` shows the lines as they are - a CSV, a log. */
  format?: "markdown" | "plain";
  className?: string;
}

/** The first lines of a document, drawn on a `DocPeek` page. */
export function TextPeek({ source, format = "markdown", className }: TextPeekProps) {
  if (format === "plain") {
    return (
      <pre
        className={cn(
          "text-muted-foreground overflow-hidden font-mono text-[11px] leading-[1.55] whitespace-pre",
          className,
        )}
      >
        {source}
      </pre>
    );
  }
  return (
    <div className={cn("space-y-0.5 overflow-hidden", className)}>
      {peekLines(source).map((line, index) => {
        if (line.kind === "gap") return <div key={index} aria-hidden className="h-1.5" />;
        if (line.kind === "heading") {
          return (
            <p
              key={index}
              className={cn(
                "font-display truncate leading-snug font-semibold",
                line.level === 1
                  ? "text-foreground text-[13px]"
                  : "text-foreground/80 text-[11.5px]",
              )}
            >
              {line.text}
            </p>
          );
        }
        if (line.kind === "item") {
          return (
            <p key={index} className="text-muted-foreground flex gap-1.5 text-xs leading-[1.55]">
              <span className="text-muted-foreground shrink-0 tabular-nums">{line.marker}</span>
              <span className="truncate">{line.text}</span>
            </p>
          );
        }
        return (
          <p key={index} className="text-muted-foreground line-clamp-2 text-xs leading-[1.55]">
            {line.text}
          </p>
        );
      })}
    </div>
  );
}
