"use client";

import { ChevronDown, ChevronUp } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { AvatarFace } from "@/components/ui/avatar-face";
import { cn } from "@/lib/utils";

/** One tick on the rail: a message, and enough of it to recognise. */
export interface RailEntry {
  id: string;
  /** Who said it - a person's own turn reads as "You". */
  author: string;
  /** The message's raw text. The card shows the opening of it, flattened. */
  preview: string;
  isUser: boolean;
  /** The agent that answered, when one did - for its picture. */
  agentId?: string;
  /** Its handle, which is what that picture is drawn from. */
  agentSlug?: string;
  /** Whether that agent has an uploaded picture, so the row can skip a 404. */
  hasAvatar?: boolean;
  /** What the person's generated face is drawn from. */
  seed: string;
}

/**
 * A message as one line of plain prose.
 *
 * The card is four centimetres wide and a message can be a page, so this is not
 * a rendering of it - it is a label. Markdown is stripped rather than rendered:
 * `**AgenticOS**` in a preview is noise either way, and a card that lays out
 * headings and bullets stops being a label and starts being a second
 * transcript. Code fences go entirely, because the first line of a block says
 * nothing about the message that carried it.
 */
export function previewOf(text: string): string {
  return (
    text
      .replace(/```[\s\S]*?```/g, " ")
      .replace(/`([^`]*)`/g, "$1")
      .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
      .replace(/\[([^\]]*)\]\(([^)]*)\)/g, "$1")
      .replace(/^\s{0,3}#{1,6}\s+/gm, "")
      .replace(/^\s*[-*+]\s+/gm, "")
      .replace(/^\s*>\s?/gm, "")
      .replace(/\*\*|__|~~/g, "")
      // A single `*` or `_` pair, where it wraps a word rather than standing on
      // its own - punctuation after it is ordinary, which is why the lookahead is
      // not just whitespace.
      .replace(/(^|\s)[*_]([^*_\n]+)[*_](?=[\s.,;:!?)\]]|$)/g, "$1$2")
      .replace(/\s+/g, " ")
      .trim()
  );
}

export interface TurnRailProps {
  entries: RailEntry[];
  className?: string;
}

/**
 * Below this a rail is more chrome than help: three ticks tell a reader nothing
 * they cannot already see by scrolling a screen.
 */
const MIN_ENTRIES = 4;

/** Scrolls a message into view, when the transcript still holds it. */
function jumpTo(id: string) {
  const anchor = document.querySelector(`[data-message-id="${CSS.escape(id)}"]`);
  anchor?.scrollIntoView({ behavior: "smooth", block: "center" });
}

/**
 * A map of the conversation down the edge of it.
 *
 * One tick per message, in order, with the tick for whatever is on screen lit.
 * Hovering one says who spoke and roughly what about; clicking it goes there.
 * The point is a long transcript: scrolling back for the message where a number
 * was quoted means reading every turn on the way, and a rail means picking it
 * out of a shape instead.
 *
 * The ticks are built from the transcript the list is already rendering rather
 * than from a query of its own, and they find their targets by the
 * `data-message-id` each row carries. So a rail can never disagree with the
 * transcript about what is in it: there is one list and this draws it sideways.
 */
export function TurnRail({ entries, className }: TurnRailProps) {
  const t = useTranslations("chat.rail");
  const [hovered, setHovered] = useState<number | null>(null);
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (entries.length < MIN_ENTRIES) return;
    // The topmost message still on screen is the one a reader is on. An observer
    // rather than a scroll handler, so nothing runs on the frames between.
    const observer = new IntersectionObserver(
      (records) => {
        const visible = records
          .filter((record) => record.isIntersecting)
          .map((record) =>
            entries.findIndex(
              (entry) => entry.id === record.target.getAttribute("data-message-id"),
            ),
          )
          .filter((index) => index >= 0);
        if (visible.length > 0) setActive(Math.min(...visible));
      },
      { rootMargin: "-10% 0px -60% 0px" },
    );
    for (const entry of entries) {
      const anchor = document.querySelector(`[data-message-id="${CSS.escape(entry.id)}"]`);
      if (anchor) observer.observe(anchor);
    }
    return () => observer.disconnect();
  }, [entries]);

  if (entries.length < MIN_ENTRIES) return null;

  const step = (delta: number) => {
    const next = Math.min(entries.length - 1, Math.max(0, active + delta));
    setActive(next);
    const entry = entries[next];
    if (entry) jumpTo(entry.id);
  };

  return (
    <nav
      aria-label={t("label")}
      className={cn(
        "pointer-events-auto absolute top-1/2 left-1 z-20 hidden -translate-y-1/2 flex-col items-center gap-1 lg:flex",
        className,
      )}
    >
      <button
        type="button"
        onClick={() => step(-1)}
        disabled={active === 0}
        aria-label={t("previous")}
        className="text-muted-foreground/50 hover:text-foreground disabled:pointer-events-none disabled:opacity-25"
      >
        <ChevronUp className="h-3.5 w-3.5" aria-hidden />
      </button>

      <ul className="flex flex-col items-start gap-1.5 py-1">
        {entries.map((entry, index) => (
          <li key={entry.id} className="relative flex items-center">
            {hovered === index && (
              // Opening away from the edge the rail is pinned to, which is the
              // only side with room for it.
              <span className="bg-popover/95 text-popover-foreground border-border/60 absolute left-6 z-10 flex w-72 items-start gap-2.5 rounded-2xl border p-2.5 shadow-xl backdrop-blur-sm">
                {entry.agentId !== undefined ? (
                  <AgentAvatar
                    agentId={entry.agentId}
                    slug={entry.agentSlug ?? ""}
                    hasAvatar={entry.hasAvatar}
                    size="sm"
                  />
                ) : (
                  <span className="h-6 w-6 shrink-0 overflow-hidden rounded-full">
                    <AvatarFace seed={entry.seed} />
                  </span>
                )}
                <span className="min-w-0">
                  <span className="text-muted-foreground block text-[11px] font-medium">
                    {entry.author}
                  </span>
                  {/* Two lines, and no more: the card is a label for a message,
                      not a second place to read it. */}
                  <span className="text-foreground/90 mt-0.5 line-clamp-2 text-[12px] leading-snug">
                    {previewOf(entry.preview) || t("empty")}
                  </span>
                </span>
              </span>
            )}
            <button
              type="button"
              onMouseEnter={() => setHovered(index)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(index)}
              onBlur={() => setHovered(null)}
              onClick={() => {
                setActive(index);
                jumpTo(entry.id);
              }}
              aria-label={t("jumpTo", { author: entry.author })}
              aria-current={index === active ? "true" : undefined}
              className="flex h-2.5 items-center px-1"
            >
              {/* A person's turn is the short mark and the agent's the long one,
                  so the shape of a conversation is readable before any of it is. */}
              <span
                className={cn(
                  "block h-px rounded-full transition-all",
                  entry.isUser ? "w-3" : "w-5",
                  index === active
                    ? "bg-foreground h-0.5"
                    : "bg-foreground/25 group-hover:bg-foreground/50",
                )}
              />
            </button>
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={() => step(1)}
        disabled={active === entries.length - 1}
        aria-label={t("next")}
        className="text-muted-foreground/50 hover:text-foreground disabled:pointer-events-none disabled:opacity-25"
      >
        <ChevronDown className="h-3.5 w-3.5" aria-hidden />
      </button>
    </nav>
  );
}
