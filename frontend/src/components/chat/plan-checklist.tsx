"use client";

import { Ban, Check, CircleDashed, Loader2, OctagonAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ComponentType } from "react";

import type { PlanStep, PlanStepStatus } from "@/lib/plan-state";
import { cn } from "@/lib/utils";

/**
 * How each status is drawn: an icon, a tint, and what it does to the text.
 *
 * A table because the two surfaces that draw a plan - the strip above the composer
 * and what opens under a planning step - have to agree on it. A checklist whose
 * glyphs mean one thing in the transcript and another above the input is a
 * checklist somebody has to read twice.
 */
const LOOK: Record<
  PlanStepStatus,
  { icon: ComponentType<{ className?: string }>; tint: string; labelKey: string }
> = {
  pending: { icon: CircleDashed, tint: "text-muted-foreground/60", labelKey: "statusPending" },
  in_progress: { icon: Loader2, tint: "text-brand", labelKey: "statusInProgress" },
  completed: { icon: Check, tint: "text-success", labelKey: "statusCompleted" },
  cancelled: { icon: Ban, tint: "text-muted-foreground/50", labelKey: "statusCancelled" },
  blocked: { icon: OctagonAlert, tint: "text-amber-600", labelKey: "statusBlocked" },
};

/**
 * The plan, one step per row.
 *
 * The step in flight is the one the eye should land on, so it keeps full contrast
 * and a turning spinner while everything settled goes quiet - struck through once
 * it is done, dimmed once it is cancelled. That ranking is the whole point of
 * drawing the checklist rather than printing the tool's text: a plan is read to
 * find out where the agent is.
 */
export function PlanChecklist({
  steps,
  className,
}: {
  steps: readonly PlanStep[];
  className?: string;
}) {
  const t = useTranslations("chat.plan");
  return (
    <ol className={cn("space-y-1.5", className)}>
      {steps.map((step, index) => {
        const look = LOOK[step.status];
        const Icon = look.icon;
        return (
          <li
            key={step.id ?? `${index}-${step.content}`}
            className="step-in flex items-start gap-2.5 text-[13px] leading-relaxed"
            style={{ animationDelay: `${Math.min(index, 8) * 24}ms` }}
          >
            <span
              aria-label={t(look.labelKey)}
              className={cn(
                "mt-[3px] flex h-3.5 w-3.5 shrink-0 items-center justify-center",
                look.tint,
              )}
            >
              <Icon
                className={cn("h-3.5 w-3.5", step.status === "in_progress" && "animate-spin")}
              />
            </span>
            <span
              className={cn(
                "min-w-0",
                step.status === "completed" && "text-muted-foreground line-through",
                step.status === "cancelled" && "text-muted-foreground/70 line-through",
                step.status === "pending" && "text-foreground/70",
                step.status === "in_progress" && "text-foreground font-medium",
              )}
            >
              {step.content}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * How much of the plan is done, as a number and a bar.
 *
 * The width is a transition rather than a keyframe: the bar moves when a step
 * completes and stays put the rest of the time, which is the only moment worth
 * animating. `role="progressbar"` so what it says out loud is the fraction, not
 * "div".
 */
export function PlanMeter({
  completed,
  total,
  percent,
}: {
  completed: number;
  total: number;
  percent: number;
}) {
  const t = useTranslations("chat.plan");
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={completed}
        aria-label={t("progress", { completed, total })}
        className="bg-foreground/10 h-1 w-16 shrink-0 overflow-hidden rounded-full"
      >
        <span
          className="bg-brand block h-full rounded-full transition-[width] duration-500 ease-out"
          style={{ width: `${percent}%` }}
        />
      </span>
      <span className="text-muted-foreground shrink-0 font-mono text-[10px] tracking-wider">
        {t("count", { completed, total })}
      </span>
    </span>
  );
}
