"use client";

import {
  ArrowDownUp,
  CircleCheck,
  Clock,
  Globe,
  Hand,
  Keyboard,
  ListChecks,
  MousePointerClick,
  OctagonAlert,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { isRunning, type Browse, type BrowseStep } from "@/lib/browse";
import { cn } from "@/lib/utils";
import type { BrowseOutcome } from "@/types";

/**
 * How an outcome reads at a glance.
 *
 * A table rather than a chain of conditions: the four outcomes are exhaustive,
 * so there is nothing to fall through to. `blocked` is not an error tone - it is
 * the browser reporting something true about the page, and colouring it like a
 * crash would teach people to retry the thing that cannot work.
 */
export const OUTCOME_TONE: Record<BrowseOutcome, string> = {
  done: "text-emerald-600 dark:text-emerald-400",
  blocked: "text-amber-600 dark:text-amber-400",
  exhausted: "text-foreground/60",
  failed: "text-destructive",
};

/** Each action as the mark a person recognises it by, the way a computer-use trace draws it. */
const OPERATION_ICON: Record<string, LucideIcon> = {
  CLICK: MousePointerClick,
  TYPE_TEXT: Keyboard,
  SELECT: ListChecks,
  SCROLL: ArrowDownUp,
  NAVIGATE: Globe,
  BACK: Undo2,
  WAIT: Clock,
  DONE: CircleCheck,
  BLOCKED: OctagonAlert,
  ASK_PERSON: Hand,
};

/** The mark for one action, a generic page for one the table does not know. */
export function OperationIcon({ operation, className }: { operation: string; className?: string }) {
  const Icon = OPERATION_ICON[operation] ?? Globe;
  return <Icon className={className} aria-hidden />;
}

/**
 * What one step did, in words, then what it was for.
 *
 * The verb is translated and the target follows as its own text, quoted by the
 * layout rather than by the sentence - a label read off a page is data, and a
 * translator cannot place it inside a sentence they never see.
 */
function ActionLine({ step, live = false }: { step: BrowseStep; live?: boolean }) {
  const t = useTranslations("chat");
  return (
    <div className="flex min-w-0 items-start gap-2.5">
      <span
        className={cn(
          "mt-px flex size-6 shrink-0 items-center justify-center rounded-md",
          live
            ? "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300"
            : "bg-muted text-foreground/60",
        )}
      >
        <OperationIcon operation={step.operation} className="size-3.5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-baseline gap-1.5 text-sm">
          <span className="text-foreground shrink-0 font-medium">
            {t("browserAction", { operation: step.operation })}
          </span>
          {/* Page-derived text. Rendered as text, never as markup. */}
          {step.target && (
            <span className="text-foreground/70 truncate" title={step.target}>
              {step.target}
            </span>
          )}
        </span>
        {/* Model-written, so text as well - what the step was for. */}
        {step.reason && (
          <span className="text-muted-foreground mt-0.5 line-clamp-2 block text-xs">
            {step.reason}
          </span>
        )}
      </span>
    </div>
  );
}

/**
 * Every step, as a trace: a line of marks down the side, each with what it did and why.
 *
 * The newest step is lit while the browse runs, so the eye lands on what the
 * browser is doing now rather than on the top of a list.
 */
export function StepTimeline({ browse }: { browse: Browse }) {
  const running = isRunning(browse);
  return (
    <ol className="relative space-y-3">
      <span className="bg-foreground/10 absolute top-3 bottom-3 left-3 w-px" aria-hidden />
      {browse.steps.map((step, index) => (
        <li key={step.step} className="relative">
          <ActionLine step={step} live={running && index === browse.steps.length - 1} />
        </li>
      ))}
    </ol>
  );
}
