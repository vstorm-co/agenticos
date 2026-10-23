"use client";

import { ExternalLink } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import {
  SuggestionMark,
  payloadText,
  urgentFirst,
  useSuggestionActions,
  useSuggestionSource,
} from "@/components/chat/suggestion-actions";
import { Button } from "@/components/ui";
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
          const url = suggestion.kind === "finding" ? payloadText(suggestion.payload.url) : "";
          const source = sourceOf(suggestion)?.name ?? tInbox(`source.${suggestion.kind}`);
          return (
            <li
              key={suggestion.id}
              role="group"
              aria-label={suggestion.title}
              className={cn(
                "hover:bg-muted/40 flex items-start gap-3 transition-colors",
                dense ? "px-1 py-2.5" : "px-4 py-3.5 sm:px-5",
              )}
            >
              <SuggestionMark suggestion={suggestion} className="bg-muted shadow-none" />
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-baseline gap-2">
                  <p className="min-w-0 truncate text-sm font-medium">{suggestion.title}</p>
                  {suggestion.urgent && (
                    <span className="bg-destructive/10 text-destructive shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium">
                      {t("urgent")}
                    </span>
                  )}
                  <span className="text-muted-foreground ml-auto shrink-0 text-xs">
                    {tInbox("sourceAt", {
                      source,
                      when: timeAgo(suggestion.created_at, tTime, locale),
                    })}
                  </span>
                </div>
                {suggestion.detail && (
                  <p
                    className={cn(
                      "text-muted-foreground mt-0.5 text-xs",
                      dense ? "line-clamp-1" : "line-clamp-2",
                    )}
                  >
                    {suggestion.detail}
                  </p>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {url && (
                    <Button asChild size="sm" variant="outline" className="h-7">
                      <a href={url} target="_blank" rel="noopener noreferrer">
                        <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                        {t("open")}
                      </a>
                    </Button>
                  )}
                  <Button type="button" size="sm" className="h-7" onClick={() => take(suggestion)}>
                    {t(`take.${suggestion.kind}`)}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="text-muted-foreground h-7"
                    onClick={() => notNow(suggestion)}
                  >
                    {t("notNow")}
                  </Button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      {dialog}
    </>
  );
}
