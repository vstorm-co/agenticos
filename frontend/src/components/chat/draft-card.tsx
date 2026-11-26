"use client";

import { useId, useState, type KeyboardEvent } from "react";
import { useTranslations } from "next-intl";
import { FilePenLine } from "lucide-react";

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
  const selected = Math.min(open, card.versions.length - 1);
  const version = card.versions[selected]!;
  const tabbed = card.versions.length > 1;
  // Arrow keys move between the tabs, wrapping, and select the one they reach.
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (step === 0) return;
    event.preventDefault();
    const next = (selected + step + card.versions.length) % card.versions.length;
    setOpen(next);
    document.getElementById(`${id}-tab-${next}`)?.focus();
  };
  return (
    <div className="bg-card border-border my-3 w-full min-w-0 overflow-hidden rounded-2xl border">
      <div className="bg-muted/25 flex items-center gap-3 px-4 py-3">
        <span className="bg-muted text-muted-foreground grid size-9 shrink-0 place-items-center rounded-lg">
          <FilePenLine className="size-4" aria-hidden />
        </span>
        <span className="min-w-0 flex-1 text-sm leading-5 font-medium wrap-anywhere">
          {card.title}
        </span>
        <span
          title={card.kind}
          className="text-muted-foreground bg-muted max-w-[35%] min-w-0 truncate rounded-md px-2 py-1 text-xs"
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
              aria-selected={index === selected}
              aria-controls={`${id}-panel`}
              tabIndex={index === selected ? 0 : -1}
              onClick={() => setOpen(index)}
              className={cn(
                "pressable-control focus-visible:ring-ring min-h-8 rounded-lg px-2.5 py-1 text-xs transition-colors focus-visible:ring-2 focus-visible:outline-none",
                index === selected
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {one.label ?? index + 1}
            </button>
          ))}
        </div>
      )}
      <div
        key={selected}
        className={tabbed ? "tab-panel" : undefined}
        data-state={tabbed ? "active" : undefined}
        id={`${id}-panel`}
        role={tabbed ? "tabpanel" : undefined}
        aria-labelledby={tabbed ? `${id}-tab-${selected}` : undefined}
      >
        {version.fields.map((field, index) => (
          <DraftSegment
            key={`${selected}:${index}`}
            field={field}
            named={version.fields.length > 1}
          />
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
