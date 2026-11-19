"use client";

import { glideOrJump } from "@/lib/motion";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

/** A bounded, horizontally scrollable tray inside the composer. */
export function AttachmentRow({
  children,
  count,
}: {
  children: React.ReactNode;
  /** How many are attached, pending ones included. Announced without adding another visual control. */
  count: number;
}) {
  const t = useTranslations("chat.input");
  const row = useRef<HTMLDivElement>(null);
  const [overflowing, setOverflowing] = useState(false);

  const measure = useCallback(() => {
    const node = row.current;
    if (node !== null) setOverflowing(node.scrollWidth > node.clientWidth + 1);
  }, []);

  // Both edges of "is there more than fits": the row changing (a file added or
  // removed) and the composer changing width. A `ResizeObserver` on the row
  // catches the second, and the effect re-runs for the first.
  useEffect(() => {
    measure();
    const node = row.current;
    if (node === null || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [measure, children]);

  function scrollBy(direction: -1 | 1): void {
    // A card and its gap, so a press moves by one card rather than by a
    // viewport-relative amount that lands mid-card.
    row.current?.scrollBy({ left: direction * 232, behavior: glideOrJump() });
  }

  return (
    <div
      role="group"
      aria-label={t("attachedCount", { count })}
      className="chat-input-attachments border-foreground/8 mx-3 flex items-center gap-2 border-b py-3"
    >
      {overflowing && (
        <Arrow direction="left" label={t("scrollAttachmentsLeft")} onClick={() => scrollBy(-1)} />
      )}

      {/* `snap-x` so a scroll settles on a card. `scrollbar-thin` rather than
          hidden: a row with no visible scrollbar and no arrows on a touch device
          is a row nobody knows scrolls. */}
      <div
        ref={row}
        className="flex min-w-0 flex-1 snap-x scrollbar-thin items-center gap-2 overflow-x-auto"
      >
        {children}
      </div>

      {overflowing && (
        <Arrow direction="right" label={t("scrollAttachmentsRight")} onClick={() => scrollBy(1)} />
      )}

      <span className="sr-only" role="status">
        {t("attachedCount", { count })}
      </span>
    </div>
  );
}

function Arrow({
  direction,
  label,
  onClick,
}: {
  direction: "left" | "right";
  label: string;
  onClick: () => void;
}) {
  const Icon = direction === "left" ? ChevronLeft : ChevronRight;

  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className={cn(
        "text-muted-foreground hover:text-foreground hover:bg-accent/60 shrink-0 rounded-md p-1",
        "transition-colors",
      )}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}
