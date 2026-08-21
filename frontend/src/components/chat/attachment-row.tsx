"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

/**
 * One row of what is attached to the message being written.
 *
 * **One row, whatever the count.** It was a wrapping grid of 224 px tiles: one
 * file looked wedged between the usage strip and the input, six were two rows,
 * and twenty were seven rows and about 850 px of composer with the message box
 * somewhere below the fold (#927). There is no cap on how many can be attached,
 * so the render has to hold - and a row that scrolls holds at any number.
 *
 * **Its own band.** The attachments used to sit in the same stack as the usage
 * strip, so `Context 5.7% · $0.0471` and three file cards read as one confused
 * header. A rule above the input, and the row belongs to the input it is about.
 *
 * The arrows appear only when there is something to scroll to, which is measured
 * rather than guessed from the count: a card is a fixed width but the composer's
 * is not, so "more than three" is right at one window size and wrong at the next.
 */
export function AttachmentRow({
  children,
  count,
}: {
  children: React.ReactNode;
  /** How many are attached, pending ones included. Shown so the row need not be scrolled to be counted. */
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
    row.current?.scrollBy({ left: direction * 184, behavior: "smooth" });
  }

  return (
    // Its own container above the composer, not a band inside it. Wedged between
    // the usage strip and the textarea, `Context 5.7% · $0.0471` and three file
    // cards read as one confused header; what is attached is a thing of its own,
    // and it sits above the box it will be sent from.
    <div className="glass mb-2 flex items-center gap-1 rounded-2xl px-3 py-2 sm:px-4">
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

      <span className="text-muted-foreground shrink-0 pl-1 text-[11px] whitespace-nowrap">
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
