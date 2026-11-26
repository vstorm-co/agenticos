"use client";

import Link from "next/link";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { SuggestionPriority } from "./suggestion-priority";
import { Skeleton } from "@/components/ui/skeleton";
import { useSuggestions } from "@/hooks/use-suggestions";
import { usePendingApprovals } from "@/hooks/use-pending-approvals";
import { SuggestionMark, urgentFirst, useSuggestionSource } from "./suggestion-actions";

import { suggestionChatPrompt } from "@/lib/suggestion-chat-prompt";

import styles from "./chat-home-inbox.module.css";

const PREVIEW_LIMIT = 2;
const INBOX_FRAME = "chat-home-inbox chat-home-hints chat-composer-width flex min-h-40 flex-col";

/** A priority-ordered preview of the same findings and proposals the Inbox shows. */
export function ChatHomeInbox({ onDiscuss }: { onDiscuss: (prompt: string) => void }) {
  const suggested = useSuggestions();
  const pending = usePendingApprovals();
  const t = useTranslations("chat.homeInbox");
  const common = useTranslations("common");
  const inbox = useTranslations("inbox");
  const draft = useTranslations("inbox.chatDraft");
  const { sourceOf } = useSuggestionSource();
  const loading = suggested.isLoading || pending.isLoading;
  const failed = suggested.error || pending.error;
  const hasCachedContent = suggested.suggestions.length > 0 || pending.count > 0;
  const items = urgentFirst(
    suggested.suggestions.toSorted((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)),
  ).slice(0, PREVIEW_LIMIT - Number(pending.count > 0));
  if (!loading && !failed && !hasCachedContent)
    return <div className={INBOX_FRAME} aria-hidden="true" />;

  return (
    <section className={INBOX_FRAME} aria-label={t("title")} aria-busy={loading}>
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
        <div aria-hidden>
          <Skeleton className="h-14 rounded-md" />
          <Skeleton className="h-14 rounded-md" />
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
                <li key={item.id} className={`chat-home-timeline-entry ${styles.entry}`}>
                  <button
                    type="button"
                    className={`chat-home-inbox-topic ${styles.topic}`}
                    onClick={() => onDiscuss(suggestionChatPrompt(item, draft))}
                  >
                    <SuggestionMark suggestion={item} className="chat-home-inbox-source" />
                    <span className="chat-home-inbox-copy">
                      <span className="sr-only">
                        {sourceOf(item)?.name ?? inbox(`source.${item.kind}`)}
                      </span>
                      <span className="chat-home-inbox-title">{item.title}</span>
                      {item.urgent && <SuggestionPriority />}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          ) : null}
        </>
      )}
      <Link
        href="/inbox"
        className="text-muted-foreground hover:text-brand mt-auto inline-flex min-h-9 items-center gap-1.5 self-end rounded-md px-2 text-xs"
      >
        {t("openInbox")}
        <ArrowRight className="size-3.5" aria-hidden />
      </Link>
    </section>
  );
}
