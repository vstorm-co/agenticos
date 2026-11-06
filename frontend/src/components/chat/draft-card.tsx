"use client";

import { useId, useState, type KeyboardEvent } from "react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import { draftsOf, type DraftCard } from "@/lib/drafts";
import type { ToolCall } from "@/types";
import { DraftSegment } from "./draft-segment";

/**
 * A draft the agent wrote: parts to copy, versions as tabs. Text is shown as
 * typed; a markdown part can be previewed, raw HTML is never interpreted.
 */
export function DraftCardView({ card }: { card: DraftCard }) {
  const t = useTranslations("chat.drafts");
  const [open, setOpen] = useState(0);
  const id = useId();
  const version = card.versions[Math.min(open, card.versions.length - 1)]!;
  const tabbed = card.versions.length > 1;
  // Arrow keys move between the tabs, wrapping, and select the one they reach.
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (step === 0) return;
    event.preventDefault();
    const next = (open + step + card.versions.length) % card.versions.length;
    setOpen(next);
    document.getElementById(`${id}-tab-${next}`)?.focus();
  };
  return (
    <div className="bg-muted/40 border-foreground/10 my-2 w-full min-w-0 overflow-hidden rounded-2xl border">
      <div className="flex items-baseline justify-between gap-3 px-3.5 py-2.5">
        <span className="min-w-0 text-sm font-medium break-words">{card.title}</span>
        <span
          title={card.kind}
          className="text-muted-foreground max-w-[40%] min-w-0 truncate font-mono text-xs tracking-wider uppercase"
        >
          {card.kind}
        </span>
      </div>
      {tabbed && (
        <div role="tablist" aria-label={t("versions")} className="flex flex-wrap gap-1 px-3.5 pb-2">
          {card.versions.map((one, index) => (
            <button
              key={index}
              type="button"
              role="tab"
              onKeyDown={onKeyDown}
              id={`${id}-tab-${index}`}
              aria-selected={index === open}
              aria-controls={`${id}-panel`}
              tabIndex={index === open ? 0 : -1}
              onClick={() => setOpen(index)}
              className={cn(
                "rounded-md px-2 py-0.5 text-xs transition-colors",
                index === open
                  ? "bg-foreground/10 text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {one.label ?? index + 1}
            </button>
          ))}
        </div>
      )}
      <div
        id={`${id}-panel`}
        role={tabbed ? "tabpanel" : undefined}
        aria-labelledby={tabbed ? `${id}-tab-${open}` : undefined}
      >
        {version.fields.map((field, index) => (
          <DraftSegment key={`${open}:${index}`} field={field} named={version.fields.length > 1} />
        ))}
      </div>
    </div>
  );
}

/** The drafts the turn's calls wrote, one card each. */
export function TurnDrafts({ calls }: { calls: ToolCall[] }) {
  const cards = draftsOf(calls);
  if (cards.length === 0) return null;
  return (
    <>
      {cards.map((card) => (
        <DraftCardView key={card.id} card={card} />
      ))}
    </>
  );
}
