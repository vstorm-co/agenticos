"use client";

import { useEffect, useRef } from "react";
import { Bot, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { roomParticipantIdentitySuffix } from "@/lib/room-participant-labels";
import type { RoomParticipantRead } from "@/types/room";

export function RoomMentionPalette({
  items,
  selectedIndex,
  onSelectIndex,
  onPick,
  onRetry,
  isLoading,
  failed,
  id,
}: {
  id: string;
  items: RoomParticipantRead[];
  selectedIndex: number;
  onSelectIndex: (index: number) => void;
  onPick: (item: RoomParticipantRead) => void;
  onRetry: () => void;
  isLoading: boolean;
  failed: boolean;
}) {
  const t = useTranslations("chat.teamRoom");
  const tParticipants = useTranslations("chat.roomParticipants");
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>(`[data-index="${selectedIndex}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  return (
    <div
      id={id}
      role="listbox"
      aria-label={t("mentionMenu")}
      className="border-foreground/10 bg-popover absolute bottom-full left-0 z-20 mb-2 max-h-72 w-full max-w-md overflow-y-auto rounded-xl border shadow-lg"
    >
      {failed ? (
        <div className="flex items-center justify-between gap-2 p-3 text-xs" role="alert">
          <span className="text-destructive">{tParticipants("mentionablesFailed")}</span>
          <button
            type="button"
            onMouseDown={(event) => event.preventDefault()}
            onClick={onRetry}
            className="underline underline-offset-2"
          >
            {tParticipants("retry")}
          </button>
        </div>
      ) : isLoading ? (
        <p className="text-muted-foreground p-3 text-xs" role="status">
          {t("mentionLoading")}
        </p>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground p-3 text-xs">{t("mentionNoMatches")}</p>
      ) : (
        <ul ref={listRef} className="py-1">
          {items.map((item, index) => {
            const heading = index === 0 || items[index - 1]?.kind !== item.kind;
            const Mark = item.kind === "agent" ? Bot : UserRound;
            const kindLabel = t(item.kind === "agent" ? "agents" : "people");
            const suffix = roomParticipantIdentitySuffix(item, items);
            const label = suffix
              ? tParticipants("duplicateName", { name: item.name, id: suffix })
              : item.name;
            const visibleSuffix = suffix ? tParticipants("identitySuffix", { id: suffix }) : null;
            const actionLabel = !item.is_member && item.can_add ? t("addBeforeMention") : null;
            return (
              <li key={`${item.kind}:${item.id}`}>
                {heading && (
                  <p className="text-muted-foreground px-3 pt-2 pb-1 text-[11px] font-medium tracking-wide uppercase">
                    {item.kind === "agent" ? t("agents") : t("people")}
                  </p>
                )}
                <div
                  id={`${id}-${index}`}
                  role="option"
                  aria-label={`${label}, ${kindLabel}${actionLabel ? `, ${actionLabel}` : ""}`}
                  aria-selected={index === selectedIndex}
                  data-index={index}
                  tabIndex={-1}
                  onMouseEnter={() => onSelectIndex(index)}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    onPick(item);
                  }}
                  className={cn(
                    "flex cursor-pointer items-center gap-2.5 px-3 py-1.5",
                    index === selectedIndex ? "bg-foreground/[0.06]" : "hover:bg-foreground/[0.03]",
                  )}
                >
                  <Mark className="text-muted-foreground size-4 shrink-0" aria-hidden />
                  <span className="min-w-0 flex-1 truncate text-sm">{item.name}</span>
                  {visibleSuffix && (
                    <span className="text-muted-foreground shrink-0 text-xs" aria-hidden>
                      {visibleSuffix}
                    </span>
                  )}
                  {actionLabel && (
                    <span className="text-muted-foreground shrink-0 text-xs">{actionLabel}</span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
