"use client";

import { ArrowLeft, ArrowRight, Check } from "lucide-react";

import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

export interface WizardStep {
  id: string;
  /** Already translated, in sentence case; the stepper styles it, the caller words it. */
  label: string;
}

interface WizardStepsProps {
  steps: WizardStep[];
  /** The id of the step on screen. */
  current: string;
  /**
   * A dot per step and only the current one named - for a narrow dialog of few
   * steps, where a bar and a name per step stretched across the header said
   * less than the form under it.
   */
  compact?: boolean;
}

/**
 * The progress at the top of a wizard dialog: one segment per step.
 *
 * A bar per step that fills as the wizard reaches it, and under it the step's
 * number and name at the size of the form's own labels. It was a row of 24px
 * circles holding icons, joined by hairlines and named in 12px uppercase
 * monospace - which read as decoration rather than as where somebody was, and
 * was the hardest text in the dialog to read. Done steps show a check; the one
 * on screen is the only label in full ink. On a phone only its name is written
 * out: four names do not fit a row there, and the bars still count the rest.
 */
export function WizardSteps({ steps, current, compact = false }: WizardStepsProps) {
  const currentIdx = steps.findIndex((step) => step.id === current);
  if (compact) {
    return (
      <div className="mt-2 flex items-center justify-center gap-2.5">
        <ol className="flex h-5 items-center gap-1.5">
          {steps.map((step, i) => {
            const active = i === currentIdx;
            return (
              <li key={step.id} aria-current={active ? "step" : undefined} className="flex">
                <span
                  aria-hidden
                  className={cn(
                    "block h-1.5 rounded-full transition-all duration-300 ease-[var(--ease-out)]",
                    active ? "w-5" : "w-1.5",
                    i <= currentIdx ? "bg-foreground" : "bg-muted-foreground/30",
                  )}
                />
                <span className="sr-only">{step.label}</span>
              </li>
            );
          })}
        </ol>
        <span aria-hidden className="text-sm leading-5 font-medium">
          {steps[currentIdx]?.label}
        </span>
      </div>
    );
  }
  return (
    <ol className="mt-4 flex gap-3">
      {steps.map((step, i) => {
        const done = i < currentIdx;
        const active = i === currentIdx;
        return (
          <li key={step.id} aria-current={active ? "step" : undefined} className="min-w-0 flex-1">
            <span className="bg-muted block h-1 overflow-hidden rounded-full">
              <span
                className={cn(
                  "bg-foreground block h-full origin-left rounded-full transition-transform duration-500 ease-[var(--ease-out)]",
                  done || active ? "scale-x-100" : "scale-x-0",
                )}
              />
            </span>
            <span className="mt-2 flex min-w-0 items-center gap-2">
              <span
                className={cn(
                  "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold tabular-nums transition-colors duration-300",
                  done || active
                    ? "bg-foreground text-background"
                    : "bg-muted text-muted-foreground",
                )}
              >
                {done ? <Check className="h-3 w-3" strokeWidth={3} /> : i + 1}
              </span>
              <span
                className={cn(
                  "truncate text-sm font-medium transition-colors duration-300",
                  active ? "text-foreground" : "text-muted-foreground max-sm:hidden",
                )}
              >
                {step.label}
              </span>
            </span>
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
