"use client";
import { Globe, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { hostOf } from "@/lib/link-brands";
import { cn } from "@/lib/utils";

import { SourceMark } from "../source-mark";

interface WebHit {
  title: string;
  url: string;
  content: string;
  score?: number | null;
}

export interface WebSearchPayload {
  query: string;
  results: WebHit[];
}

/** Parse a structured `web_search` tool result, or null if it isn't one
 *  (error string / legacy text → caller falls back to the default renderer). */
export function parseWebSearch(result: string): WebSearchPayload | null {
  try {
    const p = JSON.parse(result);
    if (p && typeof p === "object" && p.kind === "web_search" && Array.isArray(p.results)) {
      return { query: String(p.query ?? ""), results: p.results as WebHit[] };
    }
  } catch {
    /* not JSON - fall back to the raw renderer */
  }
  return null;
}

/**
 * What a web search found, as cards: the site first - its own logo where it has
 * one - then the page's title and a line of what it says.
 *
 * Cards in a grid rather than a numbered list, because what a reader scans a
 * search for is *where* the answer came from, and a column of identical rows
 * with a link icon in each made every site look the same.
 */
export function WebSearchResults({
  data,
  detailed = false,
}: {
  data: WebSearchPayload;
  /** Deep-dive view (computer panel): show relevance scores and the full snippet. */
  detailed?: boolean;
}) {
  const t = useTranslations("chat.tools");
  if (data.results.length === 0) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 py-2 text-sm">
        <Globe className="h-4 w-4" />
        {t("noWebResults")}
      </div>
    );
  }

  return (
    <div className="space-y-2.5 py-1">
      <div className="text-muted-foreground flex min-w-0 items-center gap-2 text-xs">
        <Search className="h-3.5 w-3.5 shrink-0" aria-hidden />
        {data.query ? (
          <span className="text-foreground/80 truncate font-medium">{data.query}</span>
        ) : null}
        <span aria-hidden>·</span>
        <span className="shrink-0">{t("webResultCount", { count: data.results.length })}</span>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {data.results.map((hit, i) => (
          <a
            key={`${hit.url}-${i}`}
            href={hit.url}
            target="_blank"
            rel="noopener noreferrer"
            className="border-foreground/10 hover:border-foreground/25 hover:bg-foreground/[0.02] flex min-w-0 flex-col gap-1.5 rounded-xl border p-3 transition-colors"
          >
            <span className="flex min-w-0 items-center gap-2">
              <SourceMark type="web" title={hit.title} url={hit.url} className="size-5 ring-0" />
              <span className="text-muted-foreground min-w-0 flex-1 truncate text-xs">
                {hostOf(hit.url) ?? hit.url}
              </span>
              {detailed && typeof hit.score === "number" && (
                <span className="bg-foreground/8 text-foreground/70 shrink-0 rounded px-1.5 py-0.5 font-mono text-xs tabular-nums">
                  {(hit.score * 100).toFixed(0)}%
                </span>
              )}
            </span>
            <span className="text-foreground line-clamp-2 text-[13px] leading-snug font-medium">
              {hit.title || hostOf(hit.url) || hit.url}
            </span>
            {hit.content && (
              <span
                className={cn(
                  "text-muted-foreground text-xs leading-relaxed",
                  detailed ? "whitespace-pre-wrap" : "line-clamp-2",
                )}
              >
                {hit.content}
              </span>
            )}
          </a>
        ))}
      </div>
    </div>
  );
}
