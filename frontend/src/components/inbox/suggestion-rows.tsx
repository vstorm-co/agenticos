"use client";

import Link from "next/link";
import { Check, Clock, ExternalLink, MessageSquare, MoreHorizontal } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import {
  SuggestionMark,
  urgentFirst,
  useSuggestionActions,
  useSuggestionSource,
} from "@/components/chat/suggestion-actions";
import { SuggestionPriority } from "@/components/chat/suggestion-priority";
import { Badge, Button, Skeleton } from "@/components/ui";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Suggestion } from "@/lib/suggestions-api";
import styles from "./inbox-row.module.css";
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
  showDetails = true,
  className,
}: {
  items: Suggestion[];
  dense?: boolean;
  expandedDetails?: boolean;
  showDetails?: boolean;
  className?: string;
}) {
  const t = useTranslations("chat.suggestions");
  const tInbox = useTranslations("inbox");
  const tMemory = useTranslations("pages.memory.library");
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
          const memoryId = suggestion.payload.memory_object_id;
          const memoryUrl =
            suggestion.payload.memory_mail === true &&
            typeof memoryId === "string" &&
            /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(memoryId)
              ? `/settings/memory?library=organization&object=${memoryId}`
              : null;
          const before = suggestion.payload.deadline_before;
          const after = suggestion.payload.deadline_after;
          const title = memoryUrl ? tMemory("deadlineChanged") : suggestion.title;
          const detail =
            memoryUrl && typeof before === "string" && typeof after === "string"
              ? tMemory("deadlineChange", { before, after })
              : suggestion.detail;
          const url =
            memoryUrl ??
            tableUrl ??
            (suggestion.kind === "finding" ? findingUrl(suggestion.payload.url) : null);
          const workingChat = suggestion.payload.conversation_id;
          const workingChatUrl =
            suggestion.kind === "finding" &&
            typeof workingChat === "string" &&
            /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(workingChat)
              ? `/chat?id=${encodeURIComponent(workingChat)}`
              : null;
          const server = sourceOf(suggestion);
          const source = memoryUrl
            ? tMemory("gmailSource")
            : (server?.name ?? tInbox(`source.${suggestion.kind}`));
          const waitingSource =
            !server &&
            sourceLoading &&
            suggestion.kind === "finding" &&
            typeof suggestion.payload.server === "string";
          return (
            <li
              key={suggestion.id}
              id={`suggestion-${suggestion.id}`}
              aria-label={title}
              className={cn(
                dense
                  ? "hover:bg-muted/40 grid grid-cols-[2rem_minmax(0,1fr)] items-center gap-x-3 gap-y-2 px-1 py-2.5 transition-colors @[48rem]/widget:grid-cols-[2rem_minmax(0,1fr)_auto]"
                  : styles.row,
              )}
            >
              <SuggestionMark
                suggestion={suggestion}
                className={cn("bg-muted shadow-none", !dense && styles.mark)}
              />
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 flex-wrap items-baseline gap-2">
                  <p
                    className={cn(
                      "min-w-0",
                      dense ? "text-sm font-medium" : styles.title,
                      dense ? "truncate" : "text-pretty",
                    )}
                  >
                    {url ? (
                      <Link
                        href={url}
                        target={tableUrl || memoryUrl ? undefined : "_blank"}
                        rel={tableUrl || memoryUrl ? undefined : "noopener noreferrer"}
                        className="underline-offset-4 hover:underline"
                      >
                        {title}
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
                  {suggestion.urgent && <SuggestionPriority />}
                </div>
                <span
                  className={dense ? "text-muted-foreground mt-1 block text-xs" : styles.metadata}
                >
                  {waitingSource ? (
                    <Skeleton aria-hidden className="h-4 w-32" />
                  ) : (
                    tInbox("sourceAt", {
                      source,
                      when: timeAgo(suggestion.created_at, tTime, locale),
                    })
                  )}
                </span>
                {showDetails && detail && (
                  <p
                    className={cn(
                      dense
                        ? "text-muted-foreground mt-1 max-w-3xl text-sm leading-relaxed"
                        : styles.detail,
                      dense
                        ? "line-clamp-1 @[48rem]/widget:col-span-2"
                        : !expandedDetails && "line-clamp-2",
                    )}
                  >
                    {detail}
                  </p>
                )}
              </div>
              <div
                className={cn(
                  styles.controls,
                  dense
                    ? "col-start-2 mt-0.5 flex flex-wrap items-center gap-1.5 @[48rem]/widget:col-start-3 @[48rem]/widget:row-start-1 @[48rem]/widget:self-center"
                    : styles.actions,
                )}
              >
                {dense ? (
                  <>
                    {workingChatUrl && (
                      <Button
                        asChild
                        size="sm"
                        variant="secondary"
                        className="h-9 pointer-coarse:h-11"
                      >
                        <Link href={workingChatUrl}>
                          <MessageSquare className="size-3.5" aria-hidden />
                          {tInbox("openWorkingChat")}
                        </Link>
                      </Button>
                    )}
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      className="h-9 pointer-coarse:h-11"
                      onClick={() => take(suggestion)}
                    >
                      {suggestion.kind === "finding" && <Check className="size-3.5" aria-hidden />}
                      {t(`take.${suggestion.kind}`)}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="text-muted-foreground h-9 pointer-coarse:h-11"
                      onClick={() => notNow(suggestion)}
                    >
                      <Clock className="size-3.5" aria-hidden />
                      {t("notNow")}
                    </Button>
                  </>
                ) : (
                  <>
                    <Button asChild size="sm" variant="ghost" className="h-9 pointer-coarse:h-11">
                      <Link
                        href={`/chat?new=inbox-${suggestion.id}&discuss=${suggestion.id}&answerer=agenticos`}
                      >
                        <MessageSquare className="size-3.5" aria-hidden />
                        {tInbox("discuss")}
                      </Link>
                    </Button>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          className="text-muted-foreground size-9 pointer-coarse:size-11"
                          aria-label={tInbox("moreActions", { title: suggestion.title })}
                        >
                          <MoreHorizontal className="size-4" aria-hidden />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {workingChatUrl && (
                          <DropdownMenuItem asChild>
                            <Link href={workingChatUrl}>{tInbox("openWorkingChat")}</Link>
                          </DropdownMenuItem>
                        )}
                        <DropdownMenuItem onSelect={() => take(suggestion)}>
                          {suggestion.kind === "finding" && (
                            <Check className="size-4" aria-hidden />
                          )}
                          {t(`take.${suggestion.kind}`)}
                        </DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => notNow(suggestion)}>
                          <Clock className="size-3.5" aria-hidden />
                          {t("notNow")}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </>
                )}
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
