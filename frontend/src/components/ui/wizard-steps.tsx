"use client";

import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

export interface WizardStep {
  id: string;
  /** Already translated; the stepper styles it, the caller words it. */
  label: string;
  icon: LucideIcon;
}

interface WizardStepsProps {
  steps: WizardStep[];
  /** The id of the step on screen. */
  current: string;
}

/**
 * The step timeline at the top of a wizard dialog.
 *
 * A circle per step joined by hairlines: done steps filled and checked, the
 * active one on the brand color, the rest muted. Lifted from the KB
 * sync-source wizard so every stepped dialog draws the same timeline rather
 * than each inventing its own.
 */
export function WizardSteps({ steps, current }: WizardStepsProps) {
  const currentIdx = steps.findIndex((step) => step.id === current);
  return (
    <ol className="mt-3 flex items-center gap-2">
      {steps.map((step, i) => {
        const done = i < currentIdx;
        const active = step.id === current;
        return (
          <li key={step.id} className="flex flex-1 items-center gap-2">
            <div
              className={cn(
                "flex h-6 w-6 shrink-0 items-center justify-center rounded-full transition-[background-color,color,box-shadow,transform] duration-300",
                done && "bg-foreground text-background",
                // The step on screen carries a soft halo, so it reads as "here"
                // from across the dialog rather than as one more coloured dot.
                active && "bg-brand text-brand-foreground ring-brand/15 scale-110 ring-4",
                !done && !active && "bg-foreground/8 text-muted-foreground",
              )}
            >
              {done ? <Check className="h-3 w-3" /> : <step.icon className="h-3 w-3" />}
            </div>
            <span
              className={cn(
                "hidden font-mono text-[11px] tracking-wider uppercase transition-colors duration-300 sm:inline",
                active || done ? "text-foreground" : "text-muted-foreground",
              )}
            >
              {step.label}
            </span>
            {i < steps.length - 1 && (
              // The rail fills toward the next step as the wizard advances, and
              // drains when it goes back - progress drawn as motion, not a swap.
              <span className="bg-foreground/15 relative h-px flex-1 overflow-hidden">
                <span
                  className={cn(
                    "bg-foreground absolute inset-0 origin-left transition-transform duration-500 ease-[var(--ease-out)]",
                    i < currentIdx ? "scale-x-100" : "scale-x-0",
                  )}
                />
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

interface WizardNavProps {
  /** "Back" on a later step, "Cancel" on the first - the caller words it. */
  backLabel: string;
  onBack: () => void;
  /** Draw the back arrow (a step back) rather than a plain cancel link. */
  backIsStep?: boolean;
  nextLabel: string;
  onNext: () => void;
  nextDisabled?: boolean;
  /** The last step submits: a check on the primary button, not an arrow. */
  isLast?: boolean;
  /** The submit is in flight - spinner, `busyLabel`, everything disabled. */
  busy?: boolean;
  busyLabel?: string;
}

/**
 * The footer bar of a wizard dialog: back/cancel on the left, the pill-shaped
 * primary action on the right. The same chrome as the KB sync-source wizard.
 */
export function WizardNav({
  backLabel,
  onBack,
  backIsStep = false,
  nextLabel,
  onNext,
  nextDisabled = false,
  isLast = false,
  busy = false,
  busyLabel,
}: WizardNavProps) {
  return (
    <div className="border-foreground/10 flex items-center justify-between border-t px-6 py-4">
      <button
        type="button"
        onClick={onBack}
        // A step back mid-submit would show a form the in-flight create is about
        // to answer; a cancel stays live, the way the dialog's X and Escape do.
        disabled={busy && backIsStep}
        className="text-foreground/65 hover:text-foreground inline-flex items-center gap-1.5 text-sm font-medium"
      >
        {backIsStep && <ArrowLeft className="h-4 w-4" />}
        {backLabel}
      </button>

      <button
        type="button"
        onClick={onNext}
        disabled={nextDisabled || busy}
        className="bg-foreground text-background hover:bg-foreground/90 disabled:bg-foreground/30 inline-flex items-center gap-1.5 rounded-full px-5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed"
      >
        {busy ? (
          <>
            <Spinner className="h-3.5 w-3.5" />
            {busyLabel ?? nextLabel}
          </>
        ) : (
          <>
            {nextLabel}
            {isLast ? <Check className="h-4 w-4" /> : <ArrowRight className="h-4 w-4" />}
          </>
        )}
      </button>
    </div>
  );
}
