"use client";

import { useMemo, useState } from "react";
import { Plus, Search } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
} from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import { CATEGORY_ORDER, type WidgetCategory, type WidgetDef } from "@/lib/dashboard/registry";
import { cn } from "@/lib/utils";
import { WIDGET_COMPONENTS } from "./widgets";

interface AddWidgetDialogProps {
  /** The widgets the caller may add - already gated, so nothing here leaks. */
  catalog: WidgetDef[];
  /** The period filter, so the preview shows the same data the card will. */
  period: Period;
  /**
   * How many times each widget is already on the arrangement being edited.
   * A row says so rather than disappearing or going dead: placing the same
   * card twice is allowed, and the catalog is browsed as often to check what
   * is already there as to add something new.
   */
  placed: Map<WidgetDef["id"], number>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdd: (widget: WidgetDef["id"]) => void;
}

/** A category with at least one widget matching the search, in display order. */
interface Group {
  category: WidgetCategory;
  defs: WidgetDef[];
}

/**
 * The "add a widget" catalog: search across the top, cards grouped by family so
 * a thirty-item list stays browsable, and a live preview beside it. Its list is
 * gated the same way the page is - the `catalog` prop is
 * `widgetCatalog(can, isAppAdmin)` - so it can only offer what the caller could
 * already see. Focusing or hovering a row renders that widget with its real data
 * in a fixed frame, so a person picks by what the card actually shows rather
 * than by its name; picking one does not add it here but hands it back to be
 * placed on the grid by click. A widget already on the page still appears:
 * placing the same card twice is allowed.
 */
export function AddWidgetDialog({
  catalog,
  period,
  placed,
  open,
  onOpenChange,
  onAdd,
}: AddWidgetDialogProps) {
  const t = useTranslations("dashboard");
  const [query, setQuery] = useState("");
  // Null until the person hovers or focuses a row: the preview is a response to
  // pointing at a card, and an empty pane with a hint reads better than an
  // arbitrary first card standing in for "nothing chosen yet".
  const [active, setActive] = useState<WidgetDef["id"] | null>(null);
  const PreviewWidget = active ? WIDGET_COMPONENTS[active] : null;

  // Each open is a fresh pick: a search left over from last time would hide most
  // of the catalog the moment the dialog reopens. Reset on both ways out — a
  // manual close (Radix fires onOpenChange) and picking a card (the parent closes
  // the dialog itself, so onOpenChange never fires and the row must reset too).
  const reset = () => {
    setQuery("");
    setActive(null);
  };
  const handleOpenChange = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };
  const pick = (id: WidgetDef["id"]) => {
    reset();
    onAdd(id);
  };

  // Match on the translated title and description, so the search reads what the
  // person reads. Grouping is applied after the filter, and an emptied group
  // drops out entirely.
  const groups = useMemo<Group[]>(() => {
    const needle = query.trim().toLowerCase();
    const matches = (def: WidgetDef) =>
      needle === "" ||
      t(`widgets.${def.id}.title`).toLowerCase().includes(needle) ||
      t(`widgets.${def.id}.description`).toLowerCase().includes(needle);
    const kept = catalog.filter(matches);
    return CATEGORY_ORDER.map((category) => ({
      category,
      defs: kept.filter((def) => def.category === category),
    })).filter((group) => group.defs.length > 0);
  }, [catalog, query, t]);

  const renderRow = (def: WidgetDef) => {
    const count = placed.get(def.id) ?? 0;
    return (
      <li key={def.id}>
        <button
          type="button"
          onMouseEnter={() => setActive(def.id)}
          onFocus={() => setActive(def.id)}
          onClick={() => pick(def.id)}
          className={cn(
            "border-border hover:border-brand-line hover:bg-brand-subtle/40 flex w-full items-start justify-between gap-3 rounded-lg border p-3 text-left transition-colors",
            // A card already on the page reads a step darker than the rest,
            // NEUTRAL rather than accent: the accent tint means "you are
            // pointing at this one" here, and a row that wore both meanings
            // at once said neither.
            count > 0 && "bg-muted/70 border-foreground/10",
            active === def.id && "border-brand-line bg-brand-subtle/40",
          )}
        >
          <span className="min-w-0">
            <span className="text-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium">
              {t(`widgets.${def.id}.title`)}
              {/* Words, not only a shade: the same fact has to survive a
                  greyscale screen and a reader who cannot separate the two
                  surfaces. The count is part of it because the answer to "is
                  this already there" is sometimes "twice". */}
              {count > 0 ? (
                <span className="bg-foreground/8 text-muted-foreground rounded-full px-2 py-0.5 text-[11px] font-normal">
                  {t("edit.alreadyPlaced", { count })}
                </span>
              ) : null}
            </span>
            <span className="text-muted-foreground mt-0.5 block text-xs">
              {t(`widgets.${def.id}.description`)}
            </span>
          </span>
          <span className="text-muted-foreground shrink-0" aria-hidden>
            <Plus className="size-4" />
          </span>
        </button>
      </li>
    );
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      {/* A column rather than the dialog's default grid, so the catalog and the
          preview share every pixel the viewport has left instead of each
          carrying its own `vh` cap. Wider and taller than the rest of the
          product's dialogs on purpose: this one is a browsable catalogue of
          thirty cards beside a live rendering of one, and at `3xl` the preview
          pane was too narrow to show a card at anything like its real width. */}
      <DialogContent className="flex max-h-[90vh] flex-col overflow-hidden sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>{t("edit.addTitle")}</DialogTitle>
          <DialogDescription>{t("edit.addDescription")}</DialogDescription>
        </DialogHeader>
        <div className="relative">
          <Search
            className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
            aria-hidden
          />
          <Input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label={t("edit.searchLabel")}
            placeholder={t("edit.searchPlaceholder")}
            className="pl-9"
          />
        </div>
        <div className="grid min-h-0 flex-1 gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
          <div
            role="group"
            aria-label={t("edit.addTitle")}
            className="min-h-0 space-y-4 overflow-y-auto pr-1"
          >
            {groups.length === 0 ? (
              <p className="text-muted-foreground py-8 text-center text-sm">
                {t("edit.noResults", { query: query.trim() })}
              </p>
            ) : (
              groups.map((group) => (
                <div key={group.category} className="space-y-1">
                  <p className="text-muted-foreground px-1 text-xs font-semibold tracking-wide uppercase">
                    {t(`edit.groups.${group.category}`)}
                  </p>
                  <ul className="space-y-1">{group.defs.map(renderRow)}</ul>
                </div>
              ))
            )}
          </div>
          <div className="border-border bg-muted hidden min-h-0 flex-col rounded-lg border p-3 md:flex">
            <p className="text-muted-foreground mb-2 text-xs font-medium">{t("edit.preview")}</p>
            {PreviewWidget && active ? (
              // One frame, filling the pane, so every widget previews at the same
              // size - a short card no longer looks lost and a tall one no longer
              // overflows. `min-h-80` keeps it worth looking at when the viewport
              // is short enough that `flex-1` would leave a letterbox.
              <div className="min-h-80 flex-1 overflow-hidden rounded-lg">
                <div className="pointer-events-none h-full select-none">
                  <PreviewWidget
                    title={t(`widgets.${active}.title`)}
                    hint={t(`widgets.${active}.description`)}
                    period={period}
                  />
                </div>
              </div>
            ) : (
              <p className="text-muted-foreground flex min-h-80 flex-1 items-center justify-center text-center text-xs">
                {t("edit.previewHint")}
              </p>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
