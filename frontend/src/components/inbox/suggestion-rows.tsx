"use client";

import Link from "next/link";
import { Check, ExternalLink, MessageSquare } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import {
  SuggestionMark,
  urgentFirst,
  useSuggestionActions,
  useSuggestionSource,
} from "@/components/chat/suggestion-actions";
import { Badge, Button, Skeleton } from "@/components/ui";
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
  expandedDetails = false,
  className,
}: {
  items: Suggestion[];
  dense?: boolean;
  expandedDetails?: boolean;
  className?: string;
}) {
  const t = useTranslations("chat.suggestions");
  const tInbox = useTranslations("inbox");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { sourceOf, isLoading: sourceLoading } = useSuggestionSource();
  const { take, notNow, dialog } = useSuggestionActions(null);

  return (
    <>
      <ul aria-label={t("label")} className={cn("divide-border divide-y", className)}>
        {urgentFirst(items).map((suggestion) => {
          const tableId = suggestion.payload.table_id;
          const tableUrl =
            typeof tableId === "string" && /^[0-9a-f-]{36}$/i.test(tableId)
              ? `/tables/${tableId}`
              : null;
          const url =
            tableUrl ?? (suggestion.kind === "finding" ? findingUrl(suggestion.payload.url) : null);
          const server = sourceOf(suggestion);
          const source = server?.name ?? tInbox(`source.${suggestion.kind}`);
          const waitingSource =
            !server &&
            sourceLoading &&
            suggestion.kind === "finding" &&
            typeof suggestion.payload.server === "string";
          return (
            <li
              key={suggestion.id}
              id={`suggestion-${suggestion.id}`}
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
                      <Link
                        href={url}
                        target={tableUrl ? undefined : "_blank"}
                        rel={tableUrl ? undefined : "noopener noreferrer"}
                        className="underline-offset-4 hover:underline"
                      >
                        {suggestion.title}
                        <ExternalLink
                          className="text-muted-foreground ml-1.5 inline size-3"
                          aria-hidden
                        />
                      </Link>
                    ) : (
                      suggestion.title
                    )}
                  </p>
                  {suggestion.outcome_status === "acknowledged" && (
                    <Badge variant="secondary" className="shrink-0 px-2 text-[11px]">
                      {t("acknowledged")}
                    </Badge>
                  )}
                  {suggestion.urgent && (
                    <Badge variant="destructive" className="shrink-0 px-2.5 text-xs">
                      {t("urgent")}
                    </Badge>
                  )}
                </div>
                <span className="text-muted-foreground mt-1 block text-xs">
                  {waitingSource ? (
                    <Skeleton aria-hidden className="h-4 w-32" />
                  ) : (
                    tInbox("sourceAt", {
                      source,
                      when: timeAgo(suggestion.created_at, tTime, locale),
                    })
                  )}
                </span>
                {suggestion.detail && (
                  <p
                    className={cn(
                      "text-muted-foreground mt-1 max-w-3xl text-sm leading-relaxed",
                      dense ? "line-clamp-1" : !expandedDetails && "line-clamp-2",
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
                {suggestion.kind === "finding" &&
                  typeof suggestion.payload.conversation_id === "string" &&
                  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
                    suggestion.payload.conversation_id,
                  ) && (
                    <Button asChild size="sm" variant="secondary" className="h-8">
                      <Link
                        href={`/chat?id=${encodeURIComponent(suggestion.payload.conversation_id)}`}
                      >
                        <MessageSquare className="size-3.5" aria-hidden />
                        {tInbox("openWorkingChat")}
                      </Link>
                    </Button>
                  )}
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
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
