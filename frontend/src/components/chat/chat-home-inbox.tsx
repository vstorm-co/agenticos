"use client";

import Link from "next/link";
import { ArrowUpRight, Inbox, ShieldCheck } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Skeleton } from "@/components/ui/skeleton";
import { useSuggestions } from "@/hooks/use-suggestions";
import { usePendingApprovals } from "@/hooks/use-pending-approvals";
import { timeAgo } from "@/lib/utils";
import { SuggestionMark, urgentFirst, useSuggestionSource } from "./suggestion-actions";

/** Read-only preview: decisions and source details stay in the existing Inbox. */
export function ChatHomeInbox() {
  const t = useTranslations("chat.homeInbox");
  const common = useTranslations("common");
  const inbox = useTranslations("inbox");
  const time = useTranslations("time");
  const locale = useLocale();
  const { sourceOf } = useSuggestionSource();
  const suggested = useSuggestions();
  const pending = usePendingApprovals();
  const loading = suggested.isLoading || pending.isLoading;
  const failed = suggested.error || pending.error;
  const hasCachedContent = suggested.suggestions.length > 0 || pending.count > 0;
  const items = urgentFirst(suggested.suggestions).slice(0, 3);
  return (
    <section className="chat-home-inbox" aria-label={t("title")} aria-busy={loading}>
      <div className="chat-home-inbox-header">
        <h2>
          <Inbox className="size-3.5" aria-hidden />
          {t("title")}
          {!loading && !failed && suggested.suggestions.length + pending.count > 0 && (
            <span className="chat-home-inbox-count">
              {inbox("waiting", { count: suggested.suggestions.length + pending.count })}
            </span>
          )}
        </h2>
        <Link href="/inbox">
          {t("open")}
          <ArrowUpRight className="size-3" aria-hidden />
        </Link>
      </div>
      {loading ? (
        <div className="chat-home-inbox-grid">
          {[0, 1, 2].map((key) => (
            <Skeleton key={key} className="mx-3 my-2 h-16 rounded-xl" />
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
          {(!failed || hasCachedContent) && (
            <>
              {pending.count > 0 && (
                <Link href="/runs?tab=approvals" className="chat-home-inbox-approvals">
                  <ShieldCheck className="size-3.5" aria-hidden />
                  {t("approvals", { count: pending.count })}
                  <ArrowUpRight className="ml-auto size-3" aria-hidden />
                </Link>
              )}
              {items.length > 0 ? (
                <ul className="chat-home-inbox-grid">
                  {items.map((item) => (
                    <li key={item.id}>
                      <Link href={`/inbox#suggestion-${item.id}`} className="chat-home-inbox-topic">
                        <SuggestionMark suggestion={item} className="chat-home-inbox-source" />
                        <span className="chat-home-inbox-copy">
                          <span className="chat-home-inbox-meta">
                            <span>{sourceOf(item)?.name ?? inbox(`source.${item.kind}`)}</span>
                            {item.urgent && (
                              <span className="chat-home-inbox-urgent">{t("urgent")}</span>
                            )}
                            <time dateTime={item.created_at}>
                              {timeAgo(item.created_at, time, locale)}
                            </time>
                          </span>
                          <span className="chat-home-inbox-title">{item.title}</span>
                          {item.detail && (
                            <span className="chat-home-inbox-detail">{item.detail}</span>
                          )}
                        </span>
                        <ArrowUpRight className="chat-home-inbox-arrow size-3.5" aria-hidden />
                      </Link>
                    </li>
                  ))}
                </ul>
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
