"use client";

import { useEffect } from "react";
import { Globe, Loader2, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { currentBrowse, isRunning, type Browse, type BrowseStep } from "@/lib/browse";
import { cn } from "@/lib/utils";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import type { BrowseOutcome } from "@/types";

/**
 * How an outcome reads at a glance.
 *
 * A table rather than a chain of conditions: the four outcomes are exhaustive,
 * so there is nothing to fall through to and nothing to test about falling
 * through. `blocked` is not an error tone - it is the engine reporting something
 * true about the page, and colouring it like a crash would teach people to
 * retry the thing that cannot work.
 */
const OUTCOME_TONE: Record<BrowseOutcome, string> = {
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
function Confidence({ value }: { value: number }) {
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

function StepRow({ step, last }: { step: BrowseStep; last: boolean }) {
  return (
    <li
      className={cn(
        "flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs",
        last && "bg-foreground/[0.04]",
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

function Viewport({ browse }: { browse: Browse }) {
  const t = useTranslations("chat");
  const running = isRunning(browse);

  if (!browse.image) {
    return (
      <div className="border-foreground/8 bg-foreground/[0.02] text-foreground/45 flex aspect-[4/3] w-full items-center justify-center rounded-xl border text-xs">
        {running ? t("browserWaitingForFrame") : t("browserNoPreview")}
      </div>
    );
  }
  return (
    <div className="border-foreground/8 relative overflow-hidden rounded-xl border">
      {/* eslint-disable-next-line @next/next/no-img-element -- a data: URL from
          this run's own socket, not a file the image pipeline can resolve. */}
      <img
        src={browse.image}
        alt={t("browserViewportAlt", { step: browse.imageStep })}
        className="block w-full"
      />
      {running && (
        <span className="bg-background/85 text-foreground/70 absolute top-2 right-2 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[10px] tabular-nums">
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
          {browse.maxSteps
            ? t("browserStepOf", { step: browse.imageStep, total: browse.maxSteps })
            : t("browserStep", { step: browse.imageStep })}
        </span>
      )}
    </div>
  );
}

/**
 * What the agent's browser is doing, while it is doing it.
 *
 * A `browse_page` call is the longest tool call this product makes and the only
 * one where watching is how somebody notices it acting on a page they did not
 * expect. Without this the chat shows a tool call named `browse_page` and then,
 * a minute later, a paragraph.
 *
 * **One browse at a time, and it is the running one.** A turn can browse twice;
 * two viewports side by side is two videos playing at once. A finished browse
 * stays up rather than closing the panel under somebody reading it - `blocked`
 * is an answer about the page and it is the outcome most worth reading.
 *
 * **The steps are a list, not a transcript.** Each row is what was chosen and how
 * sure the engine was, which is the pair that says whether a browse is worth
 * looking into. The page's own words appear only as an element's label and as
 * the outcome's detail, both rendered as text.
 */
export function BrowserPanel({ browses }: { browses: Browse[] }) {
  const t = useTranslations("chat");
  const { isOpen, close } = useBrowserPanelStore();
  const browse = currentBrowse(browses);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close(browse?.callId ?? null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, close, browse?.callId]);

  if (!isOpen || !browse) return null;

  return (
    <aside
      aria-label={t("browserHeading")}
      className="bg-background border-border fixed top-0 right-0 z-50 flex h-full w-[420px] flex-col border-l shadow-xl"
    >
      <div className="border-foreground/8 flex items-center justify-between gap-2 border-b px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <Globe className="text-foreground/40 h-4 w-4 shrink-0" aria-hidden />
          <div className="min-w-0">
            <h2 className="text-foreground truncate text-sm font-semibold">
              {browse.title || t("browserHeading")}
            </h2>
            {browse.url && (
              <p className="text-foreground/45 truncate font-mono text-[10px]" title={browse.url}>
                {browse.url}
              </p>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={() => close(browse.callId)}
          aria-label={t("browserClose")}
          className="text-foreground/50 hover:text-foreground hover:bg-foreground/8 shrink-0 rounded-md p-1 transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 scrollbar-thin space-y-4 overflow-y-auto px-4 py-4">
        {browse.goal && (
          <p className="text-foreground/60 text-xs leading-relaxed">
            <span className="text-foreground/40 font-mono text-[10px] tracking-wider uppercase">
              {t("browserGoal")}
            </span>
            <br />
            {browse.goal}
          </p>
        )}

        <Viewport browse={browse} />

        {browse.outcome && (
          <div className="border-foreground/8 rounded-xl border p-3">
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
        )}

        {browse.steps.length > 0 && (
          <section className="space-y-1">
            <h3 className="text-foreground/45 px-2 font-mono text-[10px] tracking-wider uppercase">
              {t("browserSteps")}
            </h3>
            <ul className="space-y-0.5">
              {browse.steps.map((step, index) => (
                <StepRow
                  key={step.step}
                  step={step}
                  last={index === browse.steps.length - 1 && isRunning(browse)}
                />
              ))}
            </ul>
          </section>
        )}
      </div>
    </aside>
  );
}
