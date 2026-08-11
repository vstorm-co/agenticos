"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import { Button } from "./button";
import { Label } from "./label";

/**
 * Controls for parameters that may be left unset, and show it.
 *
 * Extracted from the Builder's model settings, where the idiom was worked out,
 * because ingestion needs the same one for the same reason: a temperature that
 * nobody chose must not be sent, reasoning models reject it outright, and a
 * slider resting at a number is indistinguishable from a slider somebody moved
 * there. A second copy of this would eventually disagree with the first about
 * what unset looks like, and then the two pages would be saying different things
 * about the same wire format.
 */

export interface OptionalSettingProps {
  htmlFor: string;
  label: string;
  description: ReactNode;
  /** The way back to sending nothing - absent when the field is already there. */
  onReset?: () => void;
  /** What the reset offers, when "provider default" is not what unset means. */
  resetLabel?: string;
  /** Shown under the control instead of the description, and marked on it. */
  error?: string | null;
  disabled?: boolean;
  children: ReactNode;
}

/**
 * One labelled setting, with the way back to unset beside its label.
 *
 * The reset button doubles as the marker that this field *is* set: a control
 * whose value happens to equal a provider's default looks identical to one
 * nobody touched, and the difference decides whether the parameter is sent.
 */
export function OptionalSetting({
  htmlFor,
  label,
  description,
  onReset,
  resetLabel,
  error,
  disabled,
  children,
}: OptionalSettingProps) {
  const t = useTranslations("ui");
  return (
    <div className="space-y-1.5">
      <div className="flex min-h-8 items-center justify-between gap-2">
        <Label htmlFor={htmlFor}>{label}</Label>
        {onReset && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs"
            disabled={disabled}
            onClick={onReset}
          >
            {resetLabel ?? t("useProviderDefault")}
          </Button>
        )}
      </div>
      {children}
      {error ? (
        <p id={`${htmlFor}-error`} className="text-destructive text-xs">
          {error}
        </p>
      ) : (
        <p className="text-muted-foreground text-xs">{description}</p>
      )}
    </div>
  );
}

export interface OptionalSliderProps {
  id: string;
  label: string;
  description: ReactNode;
  max: number;
  step?: number;
  value: number | undefined;
  /** Where an untouched dial points - a position, never a claim. */
  resting: number;
  disabled?: boolean;
  onChange: (value: number | undefined) => void;
}

/**
 * A sampling dial, and the fact that nobody has turned it.
 *
 * A native range input rather than a component of ours: it is keyboard
 * operable, it is announced as a slider, and it needs no dependency. What it
 * cannot do is be empty, so an untouched one rests at `resting` and is muted,
 * with the readout saying so - the position is never the claim, the readout is.
 */
export function OptionalSlider({
  id,
  label,
  description,
  max,
  step = 0.05,
  value,
  resting,
  disabled,
  onChange,
}: OptionalSliderProps) {
  const t = useTranslations("ui");
  const isSet = value !== undefined;

  return (
    <OptionalSetting
      htmlFor={id}
      label={label}
      description={description}
      onReset={isSet ? () => onChange(undefined) : undefined}
      disabled={disabled}
    >
      <div className="flex items-center gap-3">
        <input
          id={id}
          type="range"
          min={0}
          max={max}
          step={step}
          value={value ?? resting}
          disabled={disabled}
          className={cn("accent-brand h-1.5 min-w-0 flex-1", !isSet && "opacity-40")}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        <span
          className={cn(
            "w-32 shrink-0 text-right font-mono text-xs",
            isSet ? "text-foreground" : "text-muted-foreground",
          )}
        >
          {isSet ? value.toFixed(2) : t("providerDefault")}
        </span>
      </div>
    </OptionalSetting>
  );
}
