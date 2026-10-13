"use client";

import {
  ArrowDownUp,
  CircleCheck,
  Clock,
  Globe,
  Keyboard,
  ListChecks,
  Lock,
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
export function ActionLine({ step, live = false }: { step: BrowseStep; live?: boolean }) {
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
 * Where the browser is, drawn as a browser draws it: a padlock, the host, the path.
 *
 * The host carries the weight because it is what a person checks - which site is
 * the agent on - and the path is there to be read when it matters.
 */
export function AddressBar({ url, className }: { url: string | null; className?: string }) {
  const t = useTranslations("chat");
  let host = "";
  let rest = "";
  let secure = false;
  if (url) {
    try {
      const parsed = new URL(url);
      host = parsed.host;
      rest = `${parsed.pathname === "/" ? "" : parsed.pathname}${parsed.search}`;
      secure = parsed.protocol === "https:";
    } catch {
      host = url;
    }
  }
  const Icon = secure ? Lock : Globe;
  return (
    <div
      className={cn(
        "bg-foreground/[0.05] text-muted-foreground flex h-7 min-w-0 items-center gap-1.5 rounded-full px-3 text-xs",
        className,
      )}
      title={url ?? undefined}
    >
      <Icon className="size-3 shrink-0" aria-hidden />
      {host ? (
        <span className="min-w-0 truncate">
          <span className="text-foreground/80 font-medium">{host}</span>
          {rest}
        </span>
      ) : (
        <span className="truncate">{t("browserStarting")}</span>
      )}
    </div>
  );
}

/** Live while the browser works, then how it ended - the one status a glance needs. */
export function LiveBadge({ browse }: { browse: Browse }) {
  const t = useTranslations("chat");
  if (browse.outcome) {
    return (
      <span
        className={cn("shrink-0 text-xs font-medium", OUTCOME_TONE[browse.outcome])}
        data-testid="card-outcome"
      >
        {t(`browserOutcome.${browse.outcome}`)}
      </span>
    );
  }
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-rose-500/10 px-2 py-0.5 text-xs font-medium text-rose-600 dark:text-rose-400">
      <span className="relative flex size-1.5" aria-hidden>
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-rose-500 opacity-60" />
        <span className="relative inline-flex size-1.5 rounded-full bg-rose-500" />
      </span>
      {t("browserLive")}
    </span>
  );
}

/**
 * How far along a browse is, in the words a caption uses.
 *
 * Reads the *picture's* step rather than the last one decided, because it
 * captions the picture - and the two can differ by one while a frame is still
 * arriving.
 */
export function useProgress(browse: Browse): string {
  const t = useTranslations("chat");
  const step = Math.max(browse.imageStep, 0);
  return browse.maxSteps
    ? t("browserStepOf", { step, total: browse.maxSteps })
    : t("browserStep", { step });
}

/**
 * The page as it looked a moment ago, framed.
 *
 * `inset` is what the card and the panel disagree about: in the panel the frame
 * is the content and gets its own border; in the card it sits inside a frame
 * already drawn, where a second one reads as a box in a box.
 */
export function Viewport({ browse, inset = false }: { browse: Browse; inset?: boolean }) {
  const t = useTranslations("chat");
  const running = isRunning(browse);

  if (!browse.image) {
    return (
      <div
        className={cn(
          "text-muted-foreground flex aspect-[4/3] w-full items-center justify-center text-xs",
          inset ? "bg-foreground/[0.03]" : "bg-foreground/[0.03] rounded-xl",
        )}
      >
        {running ? t("browserWaitingForFrame") : t("browserNoPreview")}
      </div>
    );
  }
  return (
    <div
      className={cn("relative overflow-hidden", !inset && "ring-foreground/10 rounded-xl ring-1")}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- a data: URL from
          this run's own socket, not a file the image pipeline can resolve. */}
      <img
        src={browse.image}
        alt={t("browserViewportAlt", { step: browse.imageStep })}
        className="block w-full"
      />
    </div>
  );
}

/** The outcome and what it says about the page, where both surfaces show it. */
export function Outcome({ browse }: { browse: Browse }) {
  const t = useTranslations("chat");
  if (!browse.outcome) return null;
  return (
    <div className="bg-foreground/[0.03] rounded-xl p-3">
      <p
        className={cn("text-sm font-medium", OUTCOME_TONE[browse.outcome])}
        data-testid="browse-outcome"
      >
        {t(`browserOutcome.${browse.outcome}`)}
      </p>
      {browse.detail && (
        <p className="text-muted-foreground mt-1 text-xs leading-relaxed">{browse.detail}</p>
      )}
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
