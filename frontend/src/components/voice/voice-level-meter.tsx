"use client";

import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { cn } from "@/lib/utils";

export const METER_STEPS = 5;

/** A 0..1 level as one of the meter's steps; a whisper below a fifth stays at none. */
export function meterStep(level: number): number {
  return Math.min(METER_STEPS, Math.max(0, Math.ceil(level * METER_STEPS - 0.3)));
}

/**
 * One presence's level as five bars (#54). With motion the bars ease between
 * steps; under reduced motion they jump and nothing else moves - the label
 * beside them carries the state. The call view's layout decides where it sits
 * and may add an orb on top; this is the part every proposal shares.
 */
export function VoiceLevelMeter({
  level,
  label,
  tone,
}: {
  level: number;
  /** Translated by the caller: who this is, or what they are doing. */
  label: string;
  tone: "caller" | "agent";
}) {
  const reduced = useReducedMotion();
  const step = meterStep(level);
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={METER_STEPS}
      aria-valuenow={step}
      data-motion={reduced ? "reduced" : "full"}
      className="flex h-6 items-end gap-0.5"
    >
      {Array.from({ length: METER_STEPS }, (_, index) => (
        <span
          key={index}
          aria-hidden
          className={cn(
            "w-1 rounded-full",
            tone === "agent" ? "bg-primary" : "bg-foreground",
            index < step ? "opacity-100" : "opacity-20",
            !reduced && "transition-opacity duration-150",
          )}
          style={{ height: `${((index + 1) / METER_STEPS) * 100}%` }}
        />
      ))}
    </div>
  );
}
