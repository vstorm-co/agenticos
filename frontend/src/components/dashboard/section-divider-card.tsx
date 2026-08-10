"use client";

import { ChevronDown, ChevronRight, GripVertical, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Input } from "@/components/ui";
import type { DividerEntry } from "@/lib/dashboard/layouts";
import {
  ACCENT_PRESETS,
  isAccentColour,
  isPresetAccent,
  type SectionAccent,
} from "@/lib/dashboard/registry";
import { cn } from "@/lib/utils";

interface SectionDividerCardProps {
  entry: DividerEntry;
  /** The section header is the one being dragged — reordering the whole band. */
  dragging: boolean;
  onLabelChange: (label: string) => void;
  onAccentChange: (accent: SectionAccent) => void;
  onToggleCollapse: () => void;
  onRemove: () => void;
}

const DEFAULT_CUSTOM = "#6366f1";

/**
 * A section heading in edit mode: a full-width bar carrying the caption, a
 * collapse toggle, a colour picker and a remove button. It sits *above* its
 * section's own grid rather than inside one, which is what makes each section an
 * independent surface — a card dragged out of one section's grid and into
 * another's is a real move between sections, not a card floating up across a
 * divider in one shared grid.
 *
 * The drag is owned by the editor and delegated from the grid, so only the grip
 * carries `data-section-grip` (grab the band there) and everything else carries
 * `data-no-drag` — typing a name or picking a colour never starts a reorder.
 * The colour row offers no-colour, the named presets, and a native colour input
 * for any custom colour the person wants beyond them.
 */
export function SectionDividerCard({
  entry,
  dragging,
  onLabelChange,
  onAccentChange,
  onToggleCollapse,
  onRemove,
}: SectionDividerCardProps) {
  const t = useTranslations("dashboard");
  const heading = entry.label.trim() ? entry.label : t("edit.untitledSection");
  const customActive = isAccentColour(entry.accent) && !isPresetAccent(entry.accent);
  const customValue = customActive ? entry.accent : DEFAULT_CUSTOM;

  return (
    <div
      className={cn(
        "dash-editable border-border bg-muted/30 group flex h-full flex-wrap items-center gap-2 rounded-xl border border-dashed px-2 py-1.5 transition",
        dragging && "dash-dragging",
      )}
    >
      <span
        data-section-grip
        role="presentation"
        aria-hidden
        className="text-muted-foreground hover:text-foreground flex size-7 shrink-0 cursor-grab items-center justify-center active:cursor-grabbing"
      >
        <GripVertical className="size-4" />
      </span>

      <Button
        variant="ghost"
        size="icon"
        data-no-drag
        className="text-muted-foreground hover:text-foreground size-7 shrink-0"
        aria-label={
          entry.collapsed
            ? t("edit.expand", { title: heading })
            : t("edit.collapse", { title: heading })
        }
        aria-expanded={!entry.collapsed}
        onClick={onToggleCollapse}
      >
        {entry.collapsed ? (
          <ChevronRight className="size-4" aria-hidden />
        ) : (
          <ChevronDown className="size-4" aria-hidden />
        )}
      </Button>

      <Input
        data-no-drag
        value={entry.label}
        onChange={(event) => onLabelChange(event.target.value)}
        aria-label={t("edit.sectionLabel")}
        placeholder={t("edit.sectionPlaceholder")}
        className="h-8 max-w-64 min-w-32 flex-1 border-transparent bg-transparent text-sm font-semibold shadow-none focus-visible:bg-transparent"
        maxLength={60}
      />

      <div className="ml-auto flex items-center gap-1" data-no-drag>
        <button
          type="button"
          aria-label={t("edit.accents.neutral")}
          aria-pressed={!isAccentColour(entry.accent)}
          onClick={() => onAccentChange("neutral")}
          className={cn(
            "border-muted-foreground/50 size-5 rounded-full border transition",
            !isAccentColour(entry.accent)
              ? "ring-foreground/40 ring-2 ring-offset-1"
              : "opacity-70 hover:opacity-100",
          )}
        />
        {ACCENT_PRESETS.map((accent) => (
          <button
            key={accent}
            type="button"
            aria-label={t(`edit.accents.${accent}`)}
            aria-pressed={entry.accent === accent}
            onClick={() => onAccentChange(accent)}
            // i18n-exempt: CSS class name, not copy — the accent's colour swatch
            className={cn(
              "dash-swatch size-5 rounded-full transition",
              `dash-accent-${accent}`,
              entry.accent === accent
                ? "ring-foreground/40 ring-2 ring-offset-1"
                : "opacity-70 hover:opacity-100",
            )}
          />
        ))}
        <label
          className={cn(
            "relative size-5 cursor-pointer rounded-full transition",
            customActive
              ? "ring-foreground/40 ring-2 ring-offset-1"
              : "opacity-80 hover:opacity-100",
          )}
          aria-label={t("edit.customColour")}
          title={t("edit.customColour")}
          style={
            customActive
              ? ({ background: customValue } as React.CSSProperties)
              : {
                  background:
                    // i18n-exempt: CSS gradient value, not copy — the custom-colour swatch
                    "conic-gradient(from 0deg, #ef4444, #f59e0b, #22c55e, #3b82f6, #a855f7, #ef4444)",
                }
          }
        >
          <input
            type="color"
            value={customValue}
            onChange={(event) => onAccentChange(event.target.value)}
            className="absolute inset-0 size-full cursor-pointer opacity-0"
          />
        </label>
        <Button
          variant="outline"
          size="icon"
          className="bg-card/90 text-muted-foreground hover:text-destructive ml-1 size-7"
          aria-label={t("edit.removeSection")}
          onClick={onRemove}
        >
          <Trash2 className="size-3.5" aria-hidden />
        </Button>
      </div>
    </div>
  );
}
