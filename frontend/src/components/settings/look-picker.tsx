"use client";

import { useTranslations } from "next-intl";
import { Check } from "lucide-react";
import { useRef, type KeyboardEvent } from "react";

import { LookPreview } from "./look-preview";

import { LOOKS, type Look } from "@/lib/appearance";
import { cn } from "@/lib/utils";

const NEXT_KEYS = new Set(["ArrowRight", "ArrowDown"]);
const PREVIOUS_KEYS = new Set(["ArrowLeft", "ArrowUp"]);

interface LookPickerProps {
  labelledBy: string;
  /** `undefined` before the stored look is known, which checks nothing. */
  value: Look | undefined;
  /** Whether the thumbnails are drawn dark, following the resolved theme. */
  dark: boolean;
  onChange: (look: Look) => void;
}

/**
 * The console's style, as a row of thumbnails: a radio group like
 * `ChoiceGroup`, by role and by keyboard, because a look is chosen by how it
 * looks and a word cannot show that.
 */
export function LookPicker({ labelledBy, value, dark, onChange }: LookPickerProps) {
  const t = useTranslations("appearance.looks");
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const focusable = Math.max(0, LOOKS.indexOf(value ?? "standard"));

  const onKeyDown = (event: KeyboardEvent, index: number) => {
    const step = NEXT_KEYS.has(event.key) ? 1 : PREVIOUS_KEYS.has(event.key) ? -1 : 0;
    if (step === 0) return;
    event.preventDefault();
    const next = (index + step + LOOKS.length) % LOOKS.length;
    onChange(LOOKS[next]!);
    buttons.current[next]?.focus();
  };

  return (
    <div
      role="radiogroup"
      aria-labelledby={labelledBy}
      className="grid grid-cols-[repeat(auto-fill,minmax(9rem,1fr))] gap-3"
    >
      {LOOKS.map((look, index) => {
        const checked = look === value;
        return (
          <button
            key={look}
            ref={(node) => {
              buttons.current[index] = node;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={index === focusable ? 0 : -1}
            onClick={() => onChange(look)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cn(
              "focus-visible:ring-ring flex flex-col gap-2.5 rounded-xl border p-2 text-left transition-colors outline-none focus-visible:ring-2",
              checked
                ? "border-foreground/60 bg-accent/40"
                : "hover:border-border hover:bg-accent/30 border-transparent",
            )}
          >
            <LookPreview look={look} dark={dark} />
            <span className="px-0.5">
              <span className="text-foreground flex items-center justify-between gap-2 text-sm font-medium">
                {t(`${look}.name`)}
                {checked && <Check className="h-3.5 w-3.5 shrink-0" aria-hidden />}
              </span>
              <span className="text-muted-foreground block text-xs">{t(`${look}.hint`)}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
