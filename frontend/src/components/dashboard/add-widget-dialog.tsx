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

  const renderRow = (def: WidgetDef) => (
    <li key={def.id}>
      <button
        type="button"
        onMouseEnter={() => setActive(def.id)}
        onFocus={() => setActive(def.id)}
        onClick={() => pick(def.id)}
        className={cn(
          "border-border hover:border-brand-line hover:bg-brand-subtle/40 flex w-full items-start justify-between gap-3 rounded-lg border p-3 text-left transition-colors",
          active === def.id && "border-brand-line bg-brand-subtle/40",
        )}
      >
        <span className="min-w-0">
          <span className="text-foreground block text-sm font-medium">
            {t(`widgets.${def.id}.title`)}
          </span>
          <span className="text-muted-foreground block text-xs">
            {t(`widgets.${def.id}.description`)}
          </span>
        </span>
        <span className="text-muted-foreground shrink-0" aria-hidden>
          <Plus className="size-4" />
        </span>
      </button>
    </li>
  );

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-hidden sm:max-w-3xl">
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
        <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <div
            role="group"
            aria-label={t("edit.addTitle")}
            className="max-h-[60vh] space-y-4 overflow-y-auto pr-1"
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
          <div className="border-border bg-muted/20 hidden flex-col rounded-lg border p-3 md:flex">
            <p className="text-muted-foreground mb-2 text-xs font-medium">{t("edit.preview")}</p>
            {PreviewWidget && active ? (
              // A fixed frame so every widget previews at the same size — a short
              // card no longer looks lost and a tall one no longer overflows the pane.
              <div className="h-80 overflow-hidden rounded-lg">
                <div className="pointer-events-none h-full select-none">
                  <PreviewWidget title={t(`widgets.${active}.title`)} period={period} />
                </div>
              </div>
            ) : (
              <p className="text-muted-foreground flex h-80 items-center justify-center text-center text-xs">
                {t("edit.previewHint")}
              </p>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
