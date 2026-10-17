"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { Mentionable } from "@/types/mention";
import { MentionMark } from "./mention-chip";

/**
 * The menu `@` opens above the composer: what the person may point the agent at,
 * grouped by kind, the highlighted row kept in view.
 */
export function MentionPalette({
  items,
  selectedIndex,
  onSelectIndex,
  onPick,
  isLoading,
  failed,
  full,
}: {
  items: Mentionable[];
  selectedIndex: number;
  onSelectIndex: (index: number) => void;
  onPick: (item: Mentionable) => void;
  isLoading: boolean;
  /** The list could not be read, which is said rather than shown as still loading. */
  failed: boolean;
  /** How many may be picked, when that many already are: said instead of the list. */
  full?: number;
}) {
  const t = useTranslations("chat.mentions");
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const row = listRef.current?.querySelector<HTMLElement>(`[data-index="${selectedIndex}"]`);
    row?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  return (
    <div
      role="listbox"
      aria-label={t("menu")}
      className="border-foreground/10 bg-popover absolute bottom-full left-0 z-20 mb-2 w-full max-w-md overflow-hidden rounded-xl border shadow-lg"
    >
      {full !== undefined ? (
        <p className="text-muted-foreground p-3 text-xs">{t("full", { count: full })}</p>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground p-3 text-xs">
          {failed ? t("failed") : isLoading ? t("loading") : t("nothing")}
        </p>
      ) : (
        <ul ref={listRef} className="max-h-72 overflow-y-auto py-1">
          {items.map((item, index) => {
            const heading = index === 0 || items[index - 1]?.kind !== item.kind;
            return (
              <li key={`${item.kind}:${item.id}`}>
                {heading && (
                  <p className="text-muted-foreground px-3 pt-2 pb-1 text-[11px] font-medium tracking-wide uppercase">
                    {t(`kind.${item.kind}`)}
                  </p>
                )}
                <div
                  role="option"
                  aria-selected={index === selectedIndex}
                  data-index={index}
                  tabIndex={-1}
                  onMouseEnter={() => onSelectIndex(index)}
                  onMouseDown={(event) => {
                    event.preventDefault(); // keep the textarea's focus
                    onPick(item);
                  }}
                  className={cn(
                    "flex cursor-pointer items-center gap-2.5 px-3 py-1.5",
                    index === selectedIndex ? "bg-foreground/[0.06]" : "hover:bg-foreground/[0.03]",
                  )}
                >
                  <MentionMark item={item} className="h-5 w-5 text-[9px]" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{item.name}</span>
                    {item.detail && (
                      <span className="text-muted-foreground block truncate text-xs">
                        {item.detail}
                      </span>
                    )}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
