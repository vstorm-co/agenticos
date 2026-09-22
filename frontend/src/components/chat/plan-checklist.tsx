"use client";

import { Ban, CircleDashed, Loader2, OctagonAlert } from "lucide-react";
import { motion, useReducedMotion, type Transition } from "motion/react";
import { useTranslations } from "next-intl";
import type { ComponentType, CSSProperties } from "react";

import type { PlanStep, PlanStepStatus } from "@/lib/plan-state";
import { cn } from "@/lib/utils";

/**
 * How each status is drawn: an icon, a tint, and what it does to the text.
 *
 * A table because the two surfaces that draw a plan - the strip above the composer
 * and what opens under a planning step - have to agree on it. A checklist whose
 * glyphs mean one thing in the transcript and another above the input is a
 * checklist somebody has to read twice.
 *
 * `completed` has no icon here and takes `TaskCheck` instead: a step finishing is
 * the one transition in this list worth animating, and a static tick cannot
 * carry it.
 */
const LOOK: Record<
  PlanStepStatus,
  { icon: ComponentType<{ className?: string }> | null; tint: string; labelKey: string }
> = {
  pending: { icon: CircleDashed, tint: "text-muted-foreground/60", labelKey: "statusPending" },
  in_progress: { icon: Loader2, tint: "text-brand", labelKey: "statusInProgress" },
  completed: { icon: null, tint: "text-success", labelKey: "statusCompleted" },
  cancelled: { icon: Ban, tint: "text-muted-foreground/50", labelKey: "statusCancelled" },
  blocked: { icon: OctagonAlert, tint: "text-amber-600", labelKey: "statusBlocked" },
};

/**
 * The tick, drawn rather than swapped in - the Rare UI task-list treatment
 * (`swamimalode07/rare-ui`, MIT), rebuilt around this checklist's own five
 * statuses.
 *
 * The original is an interactive checkbox with two states, and a plan is
 * neither: the agent owns these rows, nobody may click one, and `blocked` and
 * `cancelled` are outcomes a checkbox cannot say. What carried over is the
 * sequence - the dashed ring fades out, the disc scales up under it, the tick
 * draws along its own path - because that is what makes a step completing
 * read as an event rather than as a re-render.
 *
 * The colours are this codebase's: `success` for the disc, and the card's own
 * surface for the tick, so the mark still reads on a dark transcript.
 */
const RING_RADIUS = 11;
// Dashes divide the circumference, so the ring closes without a visible seam.
const RING_DASH = `1 ${(2 * Math.PI * RING_RADIUS) / 13 - 1}`;
const EASE_OUT = [0.22, 1, 0.36, 1] as const;
const INSTANT: Transition = { duration: 0 };
const FILL: Transition = { duration: 0.24, ease: EASE_OUT };
const TICK: Transition = { duration: 0.22, ease: EASE_OUT, delay: 0.06 };
const STRIKE: Transition = { duration: 0.38, ease: [0.65, 0, 0.35, 1] };

// The strike rides on the text itself, so a step that wraps gets a line per row
// rather than one line across the box the text sits in.
const STRIKE_STYLE: CSSProperties = {
  backgroundImage: "linear-gradient(currentColor, currentColor)",
  backgroundRepeat: "no-repeat",
  backgroundPosition: "0 55%",
  boxDecorationBreak: "clone",
  WebkitBoxDecorationBreak: "clone",
};

function TaskCheck({ done, timing }: { done: boolean; timing: (t: Transition) => Transition }) {
  return (
    <motion.svg
      viewBox="0 0 24 24"
      aria-hidden
      className="text-success h-3.5 w-3.5 shrink-0"
      initial={false}
    >
      <motion.circle
        cx="12"
        cy="12"
        r={RING_RADIUS}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray={RING_DASH}
        initial={false}
        animate={{ opacity: done ? 0 : 1 }}
        transition={timing(FILL)}
      />
      <motion.circle
        cx="12"
        cy="12"
        r="12"
        fill="currentColor"
        style={{ transformBox: "view-box", transformOrigin: "12px 12px" }}
        initial={false}
        animate={{ scale: done ? 1 : 0 }}
        transition={timing(FILL)}
      />
      <motion.path
        d="M7.4 12.4 10.6 15.5 16.6 8.9"
        fill="none"
        // The card underneath, not white: this checklist is drawn on both a
        // light and a dark transcript, and a white tick on a light card is a
        // disc with nothing in it.
        stroke="var(--color-card)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={false}
        animate={{ pathLength: done ? 1 : 0, opacity: done ? 1 : 0 }}
        transition={timing(TICK)}
      />
    </motion.svg>
  );
}

/**
 * The plan, one step per row.
 *
 * The step in flight is the one the eye should land on, so it keeps full contrast
 * and a turning spinner while everything settled goes quiet - struck through once
 * it is done, dimmed once it is cancelled. That ranking is the whole point of
 * drawing the checklist rather than printing the tool's text: a plan is read to
 * find out where the agent is.
 *
 * Nothing here reorders. A completed step stays where the agent put it, because
 * the order *is* the plan - sinking finished rows to the bottom, which is what an
 * interactive task list does, would rewrite the thing being reported.
 */
export function PlanChecklist({
  steps,
  className,
}: {
  steps: readonly PlanStep[];
  className?: string;
}) {
  const t = useTranslations("chat.plan");
  const reduced = useReducedMotion() ?? false;
  const timing = (transition: Transition) => (reduced ? INSTANT : transition);

  return (
    <ol className={cn("space-y-1.5", className)}>
      {steps.map((step, index) => {
        const look = LOOK[step.status];
        const Icon = look.icon;
        const done = step.status === "completed";
        const struck = done || step.status === "cancelled";
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
              {Icon === null ? (
                <TaskCheck done={done} timing={timing} />
              ) : (
                <Icon
                  className={cn("h-3.5 w-3.5", step.status === "in_progress" && "animate-spin")}
                />
              )}
            </span>
            <motion.span
              className={cn(
                "min-w-0",
                done && "text-muted-foreground",
                step.status === "cancelled" && "text-muted-foreground/70",
                step.status === "pending" && "text-foreground/70",
                step.status === "in_progress" && "text-foreground font-medium",
              )}
              style={STRIKE_STYLE}
              initial={false}
              // The rule sweeps across rather than appearing struck: a step
              // completing mid-answer is the moment this list exists to show,
              // and `line-through` shows it only to somebody already looking.
              animate={{ backgroundSize: `${struck ? 100 : 0}% 1px` }}
              transition={timing(STRIKE)}
            >
              {step.content}
            </motion.span>
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
