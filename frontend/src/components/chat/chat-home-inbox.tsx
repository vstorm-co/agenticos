"use client";

import Link from "next/link";
import { ArrowUpRight, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { Skeleton } from "@/components/ui/skeleton";
import { useSuggestions } from "@/hooks/use-suggestions";
import { usePendingApprovals } from "@/hooks/use-pending-approvals";
import { SuggestionMark, urgentFirst, useSuggestionSource } from "./suggestion-actions";

export function useChatHomeInbox() {
  const suggested = useSuggestions();
  const pending = usePendingApprovals();
  return { suggested, pending };
}

/** Read-only preview: decisions and source details stay in the existing Inbox. */
export function ChatHomeInbox({
  suggested,
  pending,
  expanded = false,
}: ReturnType<typeof useChatHomeInbox> & { expanded?: boolean }) {
  const t = useTranslations("chat.homeInbox");
  const common = useTranslations("common");
  const inbox = useTranslations("inbox");
  const { sourceOf } = useSuggestionSource();
  const loading = suggested.isLoading || pending.isLoading;
  const failed = suggested.error || pending.error;
  const hasCachedContent = suggested.suggestions.length > 0 || pending.count > 0;
  const previewLimit = expanded ? 8 : 4;
  const items = urgentFirst(suggested.suggestions).slice(
    0,
    previewLimit - Number(pending.count > 0),
  );
  return (
    <section className="chat-home-inbox" aria-label={t("title")} aria-busy={loading}>
      {loading ? (
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
                <ul>
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
                          </span>
                          <span className="chat-home-inbox-title">{item.title}</span>
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
