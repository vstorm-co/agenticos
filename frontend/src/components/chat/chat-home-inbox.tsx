"use client";

import Link from "next/link";
import { ArrowUpRight, Inbox, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { Skeleton } from "@/components/ui/skeleton";
import { useSuggestions } from "@/hooks/use-suggestions";
import { usePendingApprovals } from "@/hooks/use-pending-approvals";
import { SuggestionMark, urgentFirst } from "./suggestion-actions";

/** Read-only preview: decisions and source details stay in the existing Inbox. */
export function ChatHomeInbox() {
  const t = useTranslations("chat.homeInbox");
  const common = useTranslations("common");
  const suggested = useSuggestions();
  const pending = usePendingApprovals();
  const loading = suggested.isLoading || pending.isLoading;
  const failed = suggested.error || pending.error;
  const items = urgentFirst(suggested.suggestions).slice(0, 3);
  return (
    <section className="chat-home-inbox" aria-label={t("title")} aria-busy={loading}>
      <div className="chat-home-inbox-header">
        <h2>
          <Inbox className="size-3.5" aria-hidden />
          {t("title")}
        </h2>
        <Link href="/inbox">
          {t("open")}
          <ArrowUpRight className="size-3" aria-hidden />
        </Link>
      </div>
      {loading ? (
        <div className="chat-home-inbox-grid">
          {[0, 1, 2].map((key) => (
            <Skeleton key={key} className="h-28 rounded-2xl" />
          ))}
        </div>
      ) : failed ? (
        <div className="chat-home-inbox-notice" role="status">
          <p>{t("failed")}</p>
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
      ) : (
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
                  <Link href={`/inbox#suggestion-${item.id}`} className="chat-home-inbox-card">
                    <span className="chat-home-inbox-card-top">
                      <SuggestionMark suggestion={item} className="bg-muted shadow-none" />
                      {item.urgent && <span className="chat-home-inbox-urgent">{t("urgent")}</span>}
                      <ArrowUpRight
                        className="text-muted-foreground ml-auto size-3.5"
                        aria-hidden
                      />
                    </span>
                    <span className="chat-home-inbox-title">{item.title}</span>
                    {item.detail && <span className="chat-home-inbox-detail">{item.detail}</span>}
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            pending.count === 0 && <p className="chat-home-inbox-notice">{t("empty")}</p>
          )}
        </>
      )}
    </section>
  );
}
