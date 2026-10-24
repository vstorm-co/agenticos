"use client";

import { useRef, type KeyboardEvent } from "react";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export interface Choice<T extends string> {
  value: T;
  label: string;
  /** Drawn before the label, for a group a person scans by shape as much as by word. */
  icon?: LucideIcon;
}

interface ChoiceGroupProps<T extends string> {
  /** The id of the element naming the group. */
  labelledBy: string;
  /** `undefined` before the stored value is known, which checks nothing. */
  value: T | undefined;
  options: readonly Choice<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
}

const NEXT_KEYS = new Set(["ArrowRight", "ArrowDown"]);
const PREVIOUS_KEYS = new Set(["ArrowLeft", "ArrowUp"]);

/**
 * A compact segmented radio group: one choice of a few, applied as it is picked.
 *
 * A radio group by role and by keyboard - Tab reaches the checked choice and
 * the arrow keys move and select, wrapping at either end - because a row of
 * plain buttons styled as segments reads as one control and tabs like three.
 */
export function ChoiceGroup<T extends string>({
  labelledBy,
  value,
  options,
  onChange,
  disabled = false,
}: ChoiceGroupProps<T>) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const focusable = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  );

  const onKeyDown = (event: KeyboardEvent, index: number) => {
    const step = NEXT_KEYS.has(event.key) ? 1 : PREVIOUS_KEYS.has(event.key) ? -1 : 0;
    if (step === 0) return;
    event.preventDefault();
    const next = (index + step + options.length) % options.length;
    onChange(options[next]!.value);
    buttons.current[next]?.focus();
  };

  return (
    <div
      role="radiogroup"
      aria-labelledby={labelledBy}
      aria-disabled={disabled || undefined}
      className="border-input inline-flex flex-wrap gap-0.5 rounded-lg border p-0.5"
    >
      {options.map((option, index) => {
        const checked = option.value === value;
        return (
          <button
            key={option.value}
            ref={(node) => {
              buttons.current[index] = node;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={index === focusable ? 0 : -1}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cn(
              "focus-visible:ring-ring inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-sm transition-colors outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-60",
              checked
                ? "bg-accent text-foreground font-medium"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option.icon && <option.icon className="h-3.5 w-3.5 shrink-0" aria-hidden />}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
