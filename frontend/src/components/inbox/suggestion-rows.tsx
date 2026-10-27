"use client";

import { Check, ExternalLink } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import {
  SuggestionMark,
  urgentFirst,
  useSuggestionActions,
  useSuggestionSource,
} from "@/components/chat/suggestion-actions";
import { Badge, Button } from "@/components/ui";
import type { Suggestion } from "@/lib/suggestions-api";
import { cn, timeAgo } from "@/lib/utils";

/**
 * What waits for the person, as a mail client lists it (#2301): one row each,
 * the source's mark, the title with what it is about under it, where it came
 * from and when on the right, and the actions in the row. Urgent ones first.
 *
 * `dense` is the dashboard's briefing: one line of detail, tighter rows.
 */
export function SuggestionRows({
  items,
  dense = false,
  className,
}: {
  items: Suggestion[];
  dense?: boolean;
  className?: string;
}) {
  const t = useTranslations("chat.suggestions");
  const tInbox = useTranslations("inbox");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const sourceOf = useSuggestionSource();
  const { take, notNow, dialog } = useSuggestionActions(null);

  return (
    <>
      <ul aria-label={t("label")} className={cn("divide-border divide-y", className)}>
        {urgentFirst(items).map((suggestion) => {
          const url = suggestion.kind === "finding" ? findingUrl(suggestion.payload.url) : "";
          const source = sourceOf(suggestion)?.name ?? tInbox(`source.${suggestion.kind}`);
          return (
            <li
              key={suggestion.id}
              aria-label={suggestion.title}
              className={cn(
                "hover:bg-muted/40 grid grid-cols-[2rem_minmax(0,1fr)] items-start gap-x-3 gap-y-2 transition-colors",
                dense ? "px-1 py-2.5" : "px-4 py-5 sm:px-5 md:grid-cols-[2rem_minmax(0,1fr)_auto]",
              )}
            >
              <SuggestionMark suggestion={suggestion} className="bg-muted shadow-none" />
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-baseline gap-2">
                  <p
                    className={cn(
                      "min-w-0 text-sm font-semibold",
                      dense ? "truncate" : "text-pretty",
                    )}
                  >
                    {url ? (
                      <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline-offset-4 hover:underline"
                      >
                        {suggestion.title}
                        <ExternalLink
                          className="text-muted-foreground ml-1.5 inline size-3"
                          aria-hidden
                        />
                      </a>
                    ) : (
                      suggestion.title
                    )}
                  </p>
                  {suggestion.urgent && (
                    <Badge variant="destructive" className="shrink-0 px-2 text-[11px]">
                      {t("urgent")}
                    </Badge>
                  )}
                </div>
                <span className="text-muted-foreground mt-1 block text-xs">
                  {tInbox("sourceAt", {
                    source,
                    when: timeAgo(suggestion.created_at, tTime, locale),
                  })}
                </span>
                {suggestion.detail && (
                  <p
                    className={cn(
                      "text-muted-foreground mt-1 max-w-3xl text-sm leading-relaxed",
                      dense ? "line-clamp-1" : "line-clamp-2",
                    )}
                  >
                    {suggestion.detail}
                  </p>
                )}
              </div>
              <div
                className={cn(
                  "col-start-2 flex flex-wrap items-center gap-1.5",
                  dense ? "mt-0.5" : "md:col-start-3 md:row-start-1 md:self-center",
                )}
              >
                <Button
                  type="button"
                  size="sm"
                  variant={suggestion.kind === "finding" ? "outline" : "default"}
                  className="h-8"
                  onClick={() => take(suggestion)}
                >
                  {suggestion.kind === "finding" && <Check className="size-3.5" aria-hidden />}
                  {t(`take.${suggestion.kind}`)}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="text-muted-foreground h-8"
                  onClick={() => notNow(suggestion)}
                >
                  {t("notNow")}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
      {dialog}
    </>
  );
}

/** Findings carry external data; only web URLs without embedded credentials are links. */
function findingUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return (url.protocol === "https:" || url.protocol === "http:") && !url.username && !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}
