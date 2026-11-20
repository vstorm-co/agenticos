"use client";

import Link from "next/link";
import { ArrowUpRight, MessageSquare, ShieldCheck } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { Skeleton } from "@/components/ui/skeleton";
import { useSuggestions } from "@/hooks/use-suggestions";
import { usePendingApprovals } from "@/hooks/use-pending-approvals";
import { SuggestionMark, useSuggestionSource } from "./suggestion-actions";

/** An ordered preview of the same findings and proposals the Inbox shows. */
export function ChatHomeInbox({
  expanded = false,
  onDiscuss,
}: {
  expanded?: boolean;
  onDiscuss: (prompt: string) => void;
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
  const discussLabel = inbox("discuss");
  const items = suggested.suggestions
    .toSorted((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
    .slice(0, previewLimit - Number(pending.count > 0));
  return (
    <section
      className="chat-home-inbox chat-home-hints chat-composer-width"
      aria-label={t("title")}
      aria-busy={loading}
    >
      {!loading && pending.count > 0 && (
        <Link
          href="/runs?tab=approvals"
          aria-label={t("approvals", { count: pending.count })}
          className="text-muted-foreground hover:text-foreground mb-2 inline-flex min-h-9 items-center gap-1.5 rounded-md px-2 text-xs pointer-coarse:min-h-11"
        >
          <ShieldCheck className="size-3.5 shrink-0" aria-hidden />
          {t("approvalsLabel")}
          <span className="tabular-nums">{pending.count}</span>
        </Link>
      )}
      {loading ? (
        <div className="space-y-2" aria-hidden>
          <Skeleton className="h-8 rounded-md" />
          <Skeleton className="h-8 rounded-md" />
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
          {items.length > 0 ? (
            <ol>
              {items.map((item) => (
                <li
                  key={item.id}
                  className="chat-home-timeline-entry"
                  data-priority={item.urgent ? "" : undefined}
                >
                  {Number.isFinite(Date.parse(item.created_at)) && (
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
                    </span>
                    <ArrowUpRight className="chat-home-inbox-arrow size-3.5" aria-hidden />
                  </Link>
                  <button
                    type="button"
                    className="chat-home-inbox-discuss"
                    aria-label={discussLabel}
                    title={discussLabel}
                    onClick={() => onDiscuss(inbox("discussPrompt", { id: item.id }))}
                  >
                    <MessageSquare className="size-4" aria-hidden />
                  </button>
                </li>
              ))}
            </ol>
          ) : (
            !failed && pending.count === 0 && <p className="chat-home-inbox-notice">{t("empty")}</p>
          )}
        </>
      )}
    </section>
  );
}
