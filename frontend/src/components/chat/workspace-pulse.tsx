"use client";

import Link from "next/link";
import { ArrowUpRight, Inbox, GitBranch } from "lucide-react";
import { useTranslations } from "next-intl";

import { useSuggestions } from "@/hooks/use-suggestions";
import { useConversationTasks, taskIsActive } from "@/hooks/use-conversation-tasks";

/** A bounded handoff into decisions and ongoing work; all data stays in its existing hooks. */
export function WorkspacePulse() {
  const t = useTranslations("workspaceHome");
  const inbox = useSuggestions();
  const work = useConversationTasks(null);
  const active = work.data?.filter(taskIsActive) ?? [];
  return (
    <div className="grid gap-4 text-left sm:grid-cols-2" data-tour="workspace-pulse">
      <section className="min-w-0">
        <Link href="/inbox" className="mb-2 flex items-center gap-2 text-sm font-medium">
          <Inbox className="text-brand size-4" aria-hidden />
          {t("attention")}
          <ArrowUpRight className="text-muted-foreground ml-auto size-3.5" aria-hidden />
        </Link>
        {inbox.error ? (
          <button
            type="button"
            onClick={() => void inbox.refetch()}
            className="text-muted-foreground text-xs underline"
          >
            {t("retry")}
          </button>
        ) : inbox.isLoading ? (
          <p className="text-muted-foreground text-xs">{t("loading")}</p>
        ) : inbox.suggestions.length ? (
          <ul className="space-y-1">
            {inbox.suggestions.slice(0, 2).map((item) => (
              <li key={item.id}>
                <Link
                  href={`/inbox?item=${encodeURIComponent(item.id)}`}
                  className="hover:bg-accent block truncate rounded-md py-1.5 text-sm"
                >
                  {item.title}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground text-sm">{t("allClear")}</p>
        )}
      </section>
      <section className="min-w-0 border-t pt-4 sm:border-t-0 sm:border-l sm:pt-0 sm:pl-5">
        <Link href="/work" className="mb-2 flex items-center gap-2 text-sm font-medium">
          <GitBranch className="text-brand size-4" aria-hidden />
          {t("background")}
          <ArrowUpRight className="text-muted-foreground ml-auto size-3.5" aria-hidden />
        </Link>
        {work.error ? (
          <button
            type="button"
            onClick={() => void work.refetch()}
            className="text-muted-foreground text-xs underline"
          >
            {t("retry")}
          </button>
        ) : work.isPending ? (
          <p className="text-muted-foreground text-xs">{t("loading")}</p>
        ) : active.length ? (
          <ul className="space-y-1">
            {active.slice(0, 2).map((item) => (
              <li key={item.id}>
                <Link
                  href={`/chat?id=${encodeURIComponent(item.conversation_id)}`}
                  className="hover:bg-accent block truncate rounded-md py-1.5 text-sm"
                >
                  {item.title}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground text-sm">{t("nothingRunning")}</p>
        )}
      </section>
    </div>
  );
}
