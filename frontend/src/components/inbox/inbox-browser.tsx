"use client";

import { useLocale, useTranslations } from "next-intl";
import { useUrlState } from "@/hooks/use-url-state";
import {
  SuggestionMark,
  urgentFirst,
  useSuggestionSource,
} from "@/components/chat/suggestion-actions";
import type { Suggestion } from "@/lib/suggestions-api";
import { cn, timeAgo } from "@/lib/utils";
import { SuggestionRows } from "./suggestion-rows";

/** Keep selection in the URL so a home-screen handoff opens the same item. */
export function InboxBrowser({ items }: { items: Suggestion[] }) {
  const t = useTranslations("inbox");
  const th = useTranslations("workspaceHome");
  const tt = useTranslations("time");
  const locale = useLocale();
  const sourceOf = useSuggestionSource();
  const [selectedId, select] = useUrlState("item");
  const ordered = urgentFirst(items);
  const selected = ordered.find((item) => item.id === selectedId) ?? ordered[0];
  return (
    <div className="grid min-h-96 flex-1 md:grid-cols-[minmax(17rem,0.85fr)_minmax(0,1.4fr)]">
      <ul
        aria-label={th("attention")}
        className="max-h-60 overflow-y-auto border-b md:max-h-none md:border-r md:border-b-0"
      >
        {ordered.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              aria-pressed={selected?.id === item.id}
              onClick={() => select(item.id)}
              className={cn(
                "border-border/60 flex w-full items-start gap-3 border-b px-4 py-4 text-left transition-colors",
                selected?.id === item.id ? "bg-accent" : "hover:bg-muted/50",
              )}
            >
              <SuggestionMark suggestion={item} className="bg-muted mt-0.5 shrink-0 shadow-none" />
              <span className="min-w-0 flex-1">
                <span className="line-clamp-2 text-sm font-medium">{item.title}</span>
                {item.detail && (
                  <span className="text-muted-foreground mt-1 block truncate text-xs">
                    {item.detail}
                  </span>
                )}
                <span className="text-muted-foreground mt-2 flex items-center gap-2 text-xs">
                  <span className="truncate">
                    {sourceOf(item)?.name ?? t(`source.${item.kind}`)}
                  </span>
                  <span className="ml-auto shrink-0">{timeAgo(item.created_at, tt, locale)}</span>
                </span>
              </span>
              {item.urgent && (
                <span
                  className="bg-destructive mt-2 size-1.5 shrink-0 rounded-full"
                  aria-label={th("urgent")}
                />
              )}
            </button>
          </li>
        ))}
      </ul>
      <section aria-label={th("details")} className="bg-background/40 min-w-0 px-2 py-4 sm:p-6">
        {selected && <SuggestionRows items={[selected]} detail />}
      </section>
    </div>
  );
}
