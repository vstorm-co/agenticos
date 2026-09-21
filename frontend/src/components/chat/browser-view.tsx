"use client";

import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { isRunning, type Browse, type BrowseStep } from "@/lib/browse";
import { cn } from "@/lib/utils";
import type { BrowseOutcome } from "@/types";

/**
 * How an outcome reads at a glance.
 *
 * A table rather than a chain of conditions: the four outcomes are exhaustive,
 * so there is nothing to fall through to and nothing to test about falling
 * through. `blocked` is not an error tone - it is the engine reporting something
 * true about the page, and colouring it like a crash would teach people to retry
 * the thing that cannot work.
 */
export const OUTCOME_TONE: Record<BrowseOutcome, string> = {
  done: "text-brand",
  blocked: "text-amber-600 dark:text-amber-400",
  exhausted: "text-foreground/60",
  failed: "text-destructive",
};

/**
 * How sure the engine was, as something readable at a glance.
 *
 * The number is shown as well as the dot. This is the one property that
 * distinguishes this engine from one that writes its next action, and rounding it
 * away into three colours would throw away the reason it is on screen.
 */
export function Confidence({ value }: { value: number }) {
  const t = useTranslations("chat");
  const tone = value >= 0.7 ? "bg-brand" : value >= 0.4 ? "bg-foreground/45" : "bg-amber-500";
  return (
    <span
      className="text-foreground/45 ml-auto inline-flex shrink-0 items-center gap-1 font-mono text-[10px] tabular-nums"
      title={t("browserConfidenceHint", { value: value.toFixed(2) })}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", tone)} aria-hidden />
      {value.toFixed(2)}
    </span>
  );
}

export function StepRow({ step, last }: { step: BrowseStep; last: boolean }) {
  return (
    <li
      className={cn(
        "flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs",
        last && "bg-foreground/[0.06]",
      )}
    >
      <span className="text-foreground/40 w-5 shrink-0 text-right font-mono text-[10px] tabular-nums">
        {step.step}
      </span>
      <span className="bg-foreground/8 text-foreground/70 shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px]">
        {step.operation}
      </span>
      {/* Page-derived text. Rendered as text, never as markup. */}
      <span className="text-foreground/75 truncate" title={step.target ?? undefined}>
        {step.target}
      </span>
      {step.confidence !== null && <Confidence value={step.confidence} />}
    </li>
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
 * `inset` is what the card and the panel disagree about, in two ways. In the
 * panel the frame is the content and gets its own border; in the card it sits
 * inside a frame already drawn, where a second one reads as a box in a box. And
 * the panel draws the step counter over the picture, where there is room for it,
 * while the card says the same thing on its own line - a spinner and "Step 3 of
 * 25" over a thumbnail 128 pixels wide is the caption competing with the picture
 * it captions, and the reader is told twice either way.
 */
export function Viewport({ browse, inset = false }: { browse: Browse; inset?: boolean }) {
  const t = useTranslations("chat");
  const running = isRunning(browse);
  const progress = useProgress(browse);

  if (!browse.image) {
    return (
      <div
        className={cn(
          "text-foreground/45 flex aspect-[4/3] w-full items-center justify-center text-xs",
          !inset && "border-foreground/8 bg-foreground/[0.02] rounded-xl border",
        )}
      >
        {running ? t("browserWaitingForFrame") : t("browserNoPreview")}
      </div>
    );
  }
  return (
    <div
      className={cn("relative overflow-hidden", !inset && "border-foreground/8 rounded-xl border")}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- a data: URL from
          this run's own socket, not a file the image pipeline can resolve. */}
      <img
        src={browse.image}
        alt={t("browserViewportAlt", { step: browse.imageStep })}
        className="block w-full"
      />
      {running && !inset && (
        <span className="bg-background/70 text-foreground/80 supports-[backdrop-filter]:bg-background/45 absolute top-2 right-2 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[10px] tabular-nums backdrop-blur-md">
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
          {progress}
        </span>
      )}
    </div>
  );
}

/** The outcome and what it says about the page, where both surfaces show it. */
export function Outcome({ browse }: { browse: Browse }) {
  const t = useTranslations("chat");
  if (!browse.outcome) return null;
  return (
    <div className="border-foreground/8 bg-foreground/[0.02] rounded-xl border p-3">
      <p
        className={cn("text-xs font-medium", OUTCOME_TONE[browse.outcome])}
        data-testid="browse-outcome"
      >
        {t(`browserOutcome.${browse.outcome}`)}
      </p>
      {browse.detail && (
        <p className="text-foreground/55 mt-1 text-xs leading-relaxed">{browse.detail}</p>
      )}
    </div>
  );
}
