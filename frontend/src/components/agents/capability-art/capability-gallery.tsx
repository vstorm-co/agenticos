"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, type ReactNode } from "react";

import { Sheet, SheetClose, SheetContent, SheetTitle } from "@/components/ui";
import { SCROLL_FADE, useScrollFade } from "@/components/ui/scroll-fade";
import { cn } from "@/lib/utils";
import type { CapabilityCatalogEntry } from "@/types/agents";

import { CapabilityArt, CapabilityCard } from "./capability-card";

/** One shelf of the gallery: a category's label and the capabilities under it. */
export interface CapabilityShelf {
  name: string;
  label: string;
  entries: CapabilityCatalogEntry[];
}

/**
 * The capabilities as illustrated cards, one sideways carousel per category,
 * with the settings of the one opened in a panel from the right.
 *
 * Shelves rather than one grid: twenty-six cards in a grid is a wall to scroll
 * past before the MCP section, where a shelf per category keeps the page six
 * rows tall and says what kind of thing each card is by where it sits.
 */
export function CapabilityGallery({
  shelves,
  enabled,
  openedId,
  disabled,
  onOpen,
  onClose,
  onToggle,
  detail,
}: {
  shelves: CapabilityShelf[];
  enabled: ReadonlySet<string>;
  openedId: string | null;
  disabled?: boolean;
  onOpen: (id: string) => void;
  onClose: () => void;
  onToggle: (id: string) => void;
  /** The opened capability's settings, which the panel holds. */
  detail: ReactNode;
}) {
  const t = useTranslations("agents");
  const opened = shelves.flatMap((shelf) => shelf.entries).find((e) => e.id === openedId);
  return (
    <div className="space-y-6">
      {shelves.map((shelf) => (
        <Shelf
          key={shelf.name}
          shelf={shelf}
          enabled={enabled}
          openedId={openedId}
          disabled={disabled}
          onOpen={onOpen}
          onToggle={onToggle}
        />
      ))}
      {opened && (
        <Sheet open onOpenChange={onClose}>
          <SheetContent side="right" className="bg-background w-full overflow-y-auto sm:max-w-2xl">
            <div className="bg-background/95 sticky top-0 z-10 flex items-center gap-2 border-b px-4 py-2 backdrop-blur">
              <SheetTitle className="min-w-0 flex-1 truncate text-sm font-semibold">
                {t("capabilitySettingsTitle", { name: opened.name })}
              </SheetTitle>
              <SheetClose onClick={onClose} />
            </div>
            <div className="mx-auto max-w-md px-4 pt-4 sm:px-5">
              <CapabilityArt id={opened.id} name={opened.name} />
            </div>
            <div className="p-4 sm:p-5">{detail}</div>
          </SheetContent>
        </Sheet>
      )}
    </div>
  );
}

function Shelf({
  shelf,
  enabled,
  openedId,
  disabled,
  onOpen,
  onToggle,
}: {
  shelf: CapabilityShelf;
  enabled: ReadonlySet<string>;
  openedId: string | null;
  disabled?: boolean;
  onOpen: (id: string) => void;
  onToggle: (id: string) => void;
}) {
  const t = useTranslations("agents");
  const strip = useRef<HTMLDivElement>(null);
  useScrollFade(strip);
  const page = (direction: 1 | -1) =>
    strip.current?.scrollBy({
      left: direction * strip.current.clientWidth * 0.85,
      behavior: "smooth",
    });
  const on = shelf.entries.filter((entry) => enabled.has(entry.id)).length;
  return (
    <section aria-label={shelf.label} className="space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium">{shelf.label}</h3>
        <span className="text-muted-foreground text-xs">
          {t("capabilityShelfEnabled", { enabled: on, total: shelf.entries.length })}
        </span>
        <div className="ml-auto hidden gap-1 sm:flex">
          <button
            type="button"
            onClick={() => page(-1)}
            aria-label={t("capabilityShelfPrevious", { shelf: shelf.label })}
            className="text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] rounded-md p-1 transition-colors"
          >
            <ChevronLeft className="size-4" />
          </button>
          <button
            type="button"
            onClick={() => page(1)}
            aria-label={t("capabilityShelfNext", { shelf: shelf.label })}
            className="text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] rounded-md p-1 transition-colors"
          >
            <ChevronRight className="size-4" />
          </button>
        </div>
      </div>
      <div
        ref={strip}
        className={cn(
          "-mx-1 flex snap-x snap-mandatory scrollbar-none gap-3 overflow-x-auto scroll-smooth px-1 pb-1",
          SCROLL_FADE,
        )}
      >
        {shelf.entries.map((entry) => (
          <div key={entry.id} className="flex w-[64%] shrink-0 snap-start sm:w-[13.5rem]">
            <CapabilityCard
              entry={entry}
              enabled={enabled.has(entry.id)}
              focused={openedId === entry.id}
              disabled={disabled}
              onFocus={() => onOpen(entry.id)}
              onToggle={() => onToggle(entry.id)}
            />
          </div>
        ))}
      </div>
    </section>
  );
}
