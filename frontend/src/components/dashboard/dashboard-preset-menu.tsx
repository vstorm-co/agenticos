"use client";

import { useState } from "react";
import { Check, ChevronDown, LayoutTemplate, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import type { DashboardPreset } from "@/lib/dashboard-preset-api";
import { cn } from "@/lib/utils";

interface DashboardPresetMenuProps {
  presets: DashboardPreset[];
  /** True when a saved arrangement is showing rather than the audience default. */
  isCustom: boolean;
  /** Apply a preset by writing its entries as the active arrangement. */
  onApply: (preset: DashboardPreset) => Promise<void>;
  /** Return to the audience default (discarding the active arrangement). */
  onUseDefault: () => Promise<void>;
  /** Open the editor on an empty grid, to compose a layout from scratch. */
  onNewBlank: () => void;
  onDelete: (presetId: string) => Promise<void>;
}

/**
 * The saved-dashboards switcher, next to Customize. It lists the person's named
 * arrangements and the audience default; picking one applies it, the trash
 * removes it. Applying does not reference the preset afterwards - it copies its
 * entries into the active arrangement - so there is no "currently on preset X"
 * to show; the default is the one state this can mark, because "no saved
 * arrangement" is knowable where "which preset this arrangement came from" is
 * not.
 */
export function DashboardPresetMenu({
  presets,
  isCustom,
  onApply,
  onUseDefault,
  onNewBlank,
  onDelete,
}: DashboardPresetMenuProps) {
  const t = useTranslations("dashboard");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const run = async (action: () => Promise<void>, close: boolean) => {
    setBusy(true);
    try {
      await action();
      if (close) setOpen(false);
    } finally {
      setBusy(false);
    }
  };

  // Through `run` (not close) so `busy` disables the row: a double-click on the
  // trash would otherwise send two DELETEs, the second 404-ing and toasting a
  // failure for a delete that succeeded.
  const remove = (preset: DashboardPreset) =>
    run(async () => {
      try {
        await onDelete(preset.id);
        toast.success(t("presets.deleted", { name: preset.name }));
      } catch {
        toast.error(t("presets.deleteFailed"));
      }
    }, false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <LayoutTemplate className="size-3.5" aria-hidden />
          {t("presets.menu")}
          <ChevronDown className="size-3.5" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-1">
        <p className="text-muted-foreground px-2 py-1.5 text-xs font-medium">
          {t("presets.heading")}
        </p>
        <button
          type="button"
          disabled={busy}
          onClick={() => run(onUseDefault, true)}
          className="hover:bg-accent flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm"
        >
          <span
            className={cn("flex size-4 items-center justify-center", isCustom && "opacity-0")}
            aria-hidden
          >
            <Check className="size-3.5" />
          </span>
          {t("presets.default")}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            onNewBlank();
            setOpen(false);
          }}
          className="hover:bg-accent flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm"
        >
          <span className="flex size-4 items-center justify-center" aria-hidden>
            <Plus className="size-3.5" />
          </span>
          {t("presets.newBlank")}
        </button>

        {presets.length === 0 ? (
          <p className="text-muted-foreground px-2 py-2 text-xs">{t("presets.empty")}</p>
        ) : (
          <ul className="mt-0.5">
            {presets.map((preset) => (
              <li key={preset.id} className="group/preset flex items-center gap-1">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => run(() => onApply(preset), true)}
                  className="hover:bg-accent flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm"
                >
                  <span className="size-4 shrink-0" aria-hidden />
                  <span className="truncate">{preset.name}</span>
                </button>
                <Button
                  variant="ghost"
                  size="icon"
                  disabled={busy}
                  aria-label={t("presets.delete", { name: preset.name })}
                  className="text-muted-foreground hover:text-destructive size-7 shrink-0 opacity-0 transition-opacity group-hover/preset:opacity-100 focus-visible:opacity-100"
                  onClick={() => remove(preset)}
                >
                  <Trash2 className="size-3.5" aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}
