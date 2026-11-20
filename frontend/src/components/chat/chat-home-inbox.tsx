"use client";

import Link from "next/link";
import { ArrowUpRight, MessageSquare, ShieldCheck, Sunrise } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { Skeleton } from "@/components/ui/skeleton";
import { useSuggestions } from "@/hooks/use-suggestions";
import { usePendingApprovals } from "@/hooks/use-pending-approvals";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { ChatHomeVariant } from "./chat-home-variants";
import { SuggestionMark, urgentFirst, useSuggestionSource } from "./suggestion-actions";

/** A preview of the same findings and proposals the Inbox shows. */
export function ChatHomeInbox({
  expanded = false,
  variant,
  onDiscuss,
}: {
  expanded?: boolean;
  variant?: ChatHomeVariant;
  onDiscuss?: (prompt: string) => void;
}) {
  const suggested = useSuggestions();
  const pending = usePendingApprovals();
  const t = useTranslations("chat.homeInbox");
  const common = useTranslations("common");
  const inbox = useTranslations("inbox");
  const format = useFormatter();
  const { sourceOf } = useSuggestionSource();
  const loading = suggested.isLoading || pending.isLoading;
  const failed = suggested.error || pending.error;
  const hasCachedContent = suggested.suggestions.length > 0 || pending.count > 0;
  const previewLimit = expanded ? 8 : 4;
  const timeline = variant === "timeline";
  const journal = variant === "journal";
  const InboxList = timeline ? "ol" : "ul";
  const summary =
    variant === "calm" ||
    variant === "spotlight" ||
    variant === "shelf" ||
    variant === "commands" ||
    variant === "dock";
  const items = (
    timeline
      ? suggested.suggestions.toSorted(
          (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
        )
      : urgentFirst(suggested.suggestions)
  ).slice(0, previewLimit - Number(pending.count > 0));
  return (
    <section
      className={cn(
        "chat-home-inbox chat-home-hints chat-composer-width mt-4",
        !(timeline || journal || variant === "commands") &&
          "bg-card border-border rounded-2xl border p-2 sm:p-3",
        summary && "chat-variant-inbox-summary",
      )}
      aria-label={t("title")}
      aria-busy={loading}
    >
      <header className="flex min-h-10 flex-wrap items-center justify-between gap-x-3 gap-y-1 px-2 pb-2">
        <h3 className="flex min-w-0 items-center gap-2 text-sm font-medium">
          {!timeline && !journal && variant !== "commands" && (
            <span className="bg-muted text-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-lg">
              <Sunrise className="size-4" aria-hidden />
            </span>
          )}
          {t("title")}
          {summary && !loading && !failed && (
            <span className="text-muted-foreground text-xs font-normal">
              {inbox("waiting", { count: suggested.suggestions.length + pending.count })}
            </span>
          )}
        </h3>
        <div className="flex min-w-0 flex-wrap items-center gap-x-2">
          {!loading && pending.count > 0 && (
            <Link
              href="/runs?tab=approvals"
              aria-label={t("approvals", { count: pending.count })}
              className="text-muted-foreground hover:text-foreground hover:bg-muted flex min-h-9 items-center gap-1.5 rounded-lg px-2 text-xs pointer-coarse:min-h-11"
            >
              <ShieldCheck className="size-3.5 shrink-0" aria-hidden />
              {t("approvalsLabel")}
              <span className="bg-muted text-foreground min-w-5 rounded-full px-1 text-center text-[11px] leading-5 font-medium tabular-nums">
                {pending.count}
              </span>
            </Link>
          )}
          <Link
            href={ROUTES.INBOX}
            className="text-muted-foreground hover:text-foreground hover:bg-muted flex min-h-9 items-center gap-1.5 rounded-lg px-2 text-xs pointer-coarse:min-h-11"
          >
            {t("openInbox")}
            <ArrowUpRight className="size-3" aria-hidden />
          </Link>
        </div>
      </header>
      {loading && !summary ? (
        <div className="space-y-2 p-2">
          {[0, 1, 2, 3].map((key) => (
            <Skeleton key={key} className="h-8 rounded-lg" />
          ))}
        </div>
      ) : (
        <>
          {failed && (
            <div className="chat-home-inbox-notice" role="status">
              <p>{t(hasCachedContent ? "refreshFailed" : "failed")}</p>
              <button
                type="button"
                onClick={() => {
                  void suggested.refetch();
                  void pending.refetch();
                }}
              >
                {common("retry")}
              </button>
            </div>
          )}
          {!loading && !summary && (!failed || hasCachedContent) && (
            <>
              {items.length > 0 ? (
                <InboxList
                  className="chat-home-briefing-items"
                  role={timeline ? "list" : undefined}
                >
                  {items.map((item, index) => (
                    <li
                      key={item.id}
                      className={timeline ? "chat-variant-timeline-entry" : undefined}
                      data-priority={timeline && item.urgent ? "" : undefined}
                    >
                      {timeline && Number.isFinite(Date.parse(item.created_at)) && (
                        <time
                          dateTime={item.created_at}
                          className="text-muted-foreground text-xs tabular-nums"
                        >
                          {format.dateTime(new Date(item.created_at), {
                            day: "numeric",
                            month: "short",
                            hour: "numeric",
                            minute: "2-digit",
                          })}
                        </time>
                      )}
                      <Link href={`/inbox#suggestion-${item.id}`} className="chat-home-inbox-topic">
                        <SuggestionMark suggestion={item} className="chat-home-inbox-source" />
                        <span className="chat-home-inbox-copy">
                          <span className="chat-home-inbox-meta">
                            <span>{sourceOf(item)?.name ?? inbox(`source.${item.kind}`)}</span>
                            {item.urgent && (
                              <span className="chat-home-inbox-urgent">{t("urgent")}</span>
                            )}
                          </span>
                          <span className="chat-home-inbox-title">{item.title}</span>
                          {journal && index === 0 && item.detail && (
                            <span className="chat-variant-journal-detail text-muted-foreground line-clamp-2 text-xs">
                              {item.detail}
                            </span>
                          )}
                        </span>
                        <ArrowUpRight className="chat-home-inbox-arrow size-3.5" aria-hidden />
                      </Link>
                      {onDiscuss && (
                        <button
                          type="button"
                          className="chat-variant-discuss"
                          aria-label={inbox("discuss")}
                          title={inbox("discuss")}
                          onClick={() => onDiscuss(inbox("discussPrompt", { id: item.id }))}
                        >
                          <MessageSquare className="size-3.5 shrink-0" aria-hidden />
                          <span>{inbox("discuss")}</span>
                        </button>
                      )}
                    </li>
                  ))}
                </InboxList>
              ) : (
                !failed &&
                pending.count === 0 && <p className="chat-home-inbox-notice">{t("empty")}</p>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
