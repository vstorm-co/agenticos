"use client";

import { useRef, type KeyboardEvent } from "react";
import { useTranslations } from "next-intl";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui";
import { CHOICE_OPTION, CHOICE_SURFACE } from "@/components/ui/control-styles";
import type { RoutineToolSettingValue } from "@/lib/routine-access-api";
import { cn } from "@/lib/utils";

const NEXT_KEYS = new Set(["ArrowRight", "ArrowDown"]);
const PREVIOUS_KEYS = new Set(["ArrowLeft", "ArrowUp"]);

/**
 * Run freely / Ask first / Off for one tool, as a radio group.
 *
 * Unlike `ChoiceGroup`, one option can be refused while the others stay: a
 * refused Run freely stays focusable (`aria-disabled`) so its tooltip can say
 * why, and the arrow keys step over it.
 */
export function RoutineAccessSetting<T extends RoutineToolSettingValue>({
  label,
  describedBy,
  value,
  options,
  refused,
  allowLabel,
  disabled,
  onChange,
}: {
  label: string;
  describedBy?: string;
  value: T;
  options: readonly T[];
  /** Why Run freely is refused here; null when it is not. */
  refused: string | null;
  /** Another name for Run freely, where it means something else. */
  allowLabel?: string;
  disabled: boolean;
  onChange: (value: T) => void;
}) {
  const t = useTranslations("triggers.access");
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const usable = (option: T) => !(option === "allow" && refused !== null);
  const onKeyDown = (event: KeyboardEvent, index: number) => {
    const step = NEXT_KEYS.has(event.key) ? 1 : PREVIOUS_KEYS.has(event.key) ? -1 : 0;
    if (step === 0) return;
    event.preventDefault();
    for (let offset = 1; offset < options.length; offset++) {
      const next = (index + step * offset + options.length * offset) % options.length;
      const option = options[next];
      if (option !== undefined && usable(option)) {
        onChange(option);
        buttons.current[next]?.focus();
        return;
      }
    }
  };
  return (
    <div
      role="radiogroup"
      aria-label={label}
      aria-describedby={describedBy}
      aria-disabled={disabled || undefined}
      className={cn(CHOICE_SURFACE, "shrink-0")}
    >
      {options.map((option, index) => {
        const checked = option === value;
        const blocked = !usable(option);
        const button = (
          <button
            key={option}
            ref={(node) => {
              buttons.current[index] = node;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-disabled={blocked || undefined}
            tabIndex={checked ? 0 : -1}
            disabled={disabled}
            onClick={() => !blocked && onChange(option)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cn(
              CHOICE_OPTION,
              "min-h-8",
              blocked && "cursor-not-allowed opacity-50",
              checked
                ? "bg-control-active text-foreground font-semibold"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option === "allow" && allowLabel !== undefined
              ? allowLabel
              : t(option as RoutineToolSettingValue)}
          </button>
        );
        return blocked ? (
          <Tooltip key={option}>
            <TooltipTrigger asChild>{button}</TooltipTrigger>
            <TooltipContent>{refused}</TooltipContent>
          </Tooltip>
        ) : (
          button
        );
      })}
    </div>
  );
}
