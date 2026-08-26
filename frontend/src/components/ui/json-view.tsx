"use client";

import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

/**
 * JSON somebody has to read, rather than JSON pretty-printed.
 *
 * `JSON.stringify(value, null, 2)` in a `<pre>` is the honest floor and it fails
 * on exactly the payloads worth opening: a chunk of parsed text is a 500-character
 * string with escaped newlines in it, so every record ran off the right edge and
 * the document became a horizontal scrollbar. What a reader needs is the shape
 * first - how many records, what each holds - and the long values on demand.
 *
 * So: every object and array folds, long strings wrap and clamp with a control to
 * see the rest, and `\n` inside a string is drawn as a line break because that is
 * what it is. The raw text is still one click away wherever this is used - the
 * caller keeps the copy button - because a reader that cannot be pasted into `jq`
 * has taken something away.
 *
 * No dependency: a JSON tree is a hundred lines of recursion, and the ones on npm
 * arrive with a theme system to fight and 200KB to ship.
 */
export function JsonView({
  value,
  /** How deep to open on arrival. Below this, nodes start folded. */
  initialDepth = 2,
  className,
}: {
  value: unknown;
  initialDepth?: number;
  className?: string;
}) {
  return (
    <div className={cn("font-mono text-[11.5px] leading-relaxed", className)}>
      <Node value={value} depth={0} initialDepth={initialDepth} />
    </div>
  );
}

/** How many lines of a string to show before offering the rest.
 *
 * Tailwind cannot build a class from a variable, so `line-clamp-4` below is the
 * other half of this number and the two have to move together. */
const CLAMP_LINES = 4;

function Node({
  name,
  value,
  depth,
  initialDepth,
}: {
  name?: string;
  value: unknown;
  depth: number;
  initialDepth: number;
}) {
  const t = useTranslations("ui");
  const [open, setOpen] = useState(depth < initialDepth);

  const entries =
    Array.isArray(value) || (typeof value === "object" && value !== null)
      ? Object.entries(value as Record<string, unknown>)
      : null;

  if (entries === null) {
    return (
      <div className="flex min-w-0 gap-2">
        {name !== undefined && <Key name={name} />}
        <Leaf value={value} />
      </div>
    );
  }

  const isArray = Array.isArray(value);
  // The brackets are drawn either side rather than written into the message: a
  // literal `{` in an ICU string opens a placeholder, and escaping one to say
  // "2 keys" is a translator's trap for no gain.
  const [openBracket, closeBracket] = isArray ? ["[", "]"] : ["{", "}"];
  const summary = isArray
    ? t("jsonItems", { count: entries.length })
    : t("jsonKeys", { count: entries.length });

  return (
    <div className="min-w-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
        className="hover:text-foreground text-muted-foreground flex min-w-0 items-center gap-1 text-left"
      >
        <ChevronRight
          className={cn("h-3 w-3 shrink-0 transition-transform", open && "rotate-90")}
        />
        {name !== undefined && <Key name={name} />}
        <span className="text-muted-foreground/70">
          {open ? openBracket : `${openBracket} ${summary} ${closeBracket}`}
        </span>
      </button>
      {open && (
        <div className="border-foreground/10 ml-[7px] border-l pl-3">
          {entries.map(([key, child]) => (
            <Node
              key={key}
              name={isArray ? undefined : key}
              value={child}
              depth={depth + 1}
              initialDepth={initialDepth}
            />
          ))}
        </div>
      )}
      {open && <span className="text-muted-foreground/70 ml-[7px] block pl-3">{closeBracket}</span>}
    </div>
  );
}

function Key({ name }: { name: string }) {
  return <span className="text-muted-foreground shrink-0">{name}:</span>;
}

/**
 * One value that is not a container.
 *
 * A string is the only one worth any effort, and it gets all of it: newlines
 * drawn as newlines, wrapped rather than scrolled, and clamped to four lines with
 * the length of what is hidden - a parsed chunk is half a page of text, and a
 * record whose value is half a page is a record you cannot see the next one from.
 */
function Leaf({ value }: { value: unknown }) {
  const t = useTranslations("ui");
  const [expanded, setExpanded] = useState(false);

  if (typeof value === "string") {
    const lines = value.split("\n");
    const long = lines.length > CLAMP_LINES || value.length > 400;
    return (
      <span className="min-w-0">
        <span
          className={cn(
            "text-foreground/85 block break-words whitespace-pre-wrap",
            long && !expanded && "line-clamp-4",
          )}
        >
          {value}
        </span>
        {long && (
          <button
            type="button"
            onClick={() => setExpanded((was) => !was)}
            className="text-brand hover:underline"
          >
            {expanded ? t("jsonShowLess") : t("jsonShowAll", { count: value.length })}
          </button>
        )}
      </span>
    );
  }

  return (
    <span
      className={cn(
        "break-words",
        typeof value === "number" && "text-brand",
        typeof value === "boolean" && "text-success",
        value === null && "text-muted-foreground/70",
      )}
    >
      {value === null ? "null" : String(value)}
    </span>
  );
}
