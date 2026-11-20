"use client";

import Link from "next/link";
import { MessageSquare, ShieldCheck } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useSuggestions } from "@/hooks/use-suggestions";
import { usePendingApprovals } from "@/hooks/use-pending-approvals";
import { SuggestionMark, urgentFirst, useSuggestionSource } from "./suggestion-actions";

const PREVIEW_LIMIT = 4;

/** A priority-ordered preview of the same findings and proposals the Inbox shows. */
export function ChatHomeInbox({ onDiscuss }: { onDiscuss: (prompt: string) => void }) {
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
  const discussLabel = inbox("discuss");
  const items = urgentFirst(
    suggested.suggestions.toSorted((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)),
  ).slice(0, PREVIEW_LIMIT - Number(pending.count > 0));
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
                <li key={item.id} className="chat-home-timeline-entry">
                  {Number.isFinite(Date.parse(item.created_at)) && (
                    <time
                      dateTime={item.created_at}
                      className="text-muted-foreground text-xs tabular-nums"
                    >
                      {format.dateTime(new Date(item.created_at), {
                        day: "numeric",
                        month: "short",
                      })}
                    </time>
                  )}
                  <Link href={`/inbox#suggestion-${item.id}`} className="chat-home-inbox-topic">
                    <SuggestionMark suggestion={item} className="chat-home-inbox-source" />
                    <span className="chat-home-inbox-copy">
                      <span className="sr-only">
                        {sourceOf(item)?.name ?? inbox(`source.${item.kind}`)}
                      </span>
                      <span className="chat-home-inbox-title">{item.title}</span>
                      {item.urgent && (
                        <Badge variant="warning" className="shrink-0 px-2 py-0 text-[11px]">
                          {t("urgent")}
                        </Badge>
                      )}
                    </span>
                  </Link>
                  <button
                    type="button"
                    className="chat-home-inbox-discuss"
                    aria-label={discussLabel}
                    title={discussLabel}
                    onClick={() => onDiscuss(inbox("discussPrompt", { id: item.id }))}
                  >
                    <MessageSquare className="size-[18px]" aria-hidden />
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
