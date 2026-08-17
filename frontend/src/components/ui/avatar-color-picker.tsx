"use client";

import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { AVATAR_COLORS } from "@/lib/avatar-color";
import { cn } from "@/lib/utils";

export interface AvatarColorPickerProps {
  /** The chosen slot (1..10), or null for auto (the id-derived default). */
  value: number | null;
  onChange: (slot: number | null) => void;
  disabled?: boolean;
  className?: string;
}

const SWATCH = "h-7 w-7 rounded-full border border-border/60 transition-shadow outline-none";
const SELECTED = "ring-ring ring-offset-background ring-2 ring-offset-2";

/**
 * Pick the colour a fallback avatar wears, or leave it automatic.
 *
 * A radio group of the ten `--avatar-*` swatches plus an "auto" that hands the
 * colour back to the hash of the id - the same finite palette the avatar draws
 * from, so a choice can never land off the design system or on an unreadable
 * fill. It renders no preview of its own; the caller shows a live avatar beside
 * it.
 */
export function AvatarColorPicker({
  value,
  onChange,
  disabled,
  className,
}: AvatarColorPickerProps) {
  const t = useTranslations("avatarColor");
  return (
    <div
      role="radiogroup"
      aria-label={t("label")}
      className={cn("flex flex-wrap items-center gap-2", className)}
    >
      <button
        type="button"
        role="radio"
        aria-checked={value == null}
        aria-label={t("auto")}
        disabled={disabled}
        onClick={() => onChange(null)}
        className={cn(
          SWATCH,
          "bg-muted text-muted-foreground flex items-center justify-center disabled:opacity-50",
          value == null && SELECTED,
        )}
      >
        <Sparkles className="h-3.5 w-3.5" aria-hidden />
      </button>
      {AVATAR_COLORS.map(({ slot, palette }) => (
        <button
          key={slot}
          type="button"
          role="radio"
          aria-checked={value === slot}
          aria-label={t("option", { n: slot })}
          disabled={disabled}
          onClick={() => onChange(slot)}
          className={cn(SWATCH, palette.bg, "disabled:opacity-50", value === slot && SELECTED)}
        />
      ))}
    </div>
  );
}
