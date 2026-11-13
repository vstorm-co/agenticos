"use client";

import { useTranslations } from "next-intl";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { SetupHint } from "@/lib/setup-hints";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { cn } from "@/lib/utils";

/** A non-blocking configuration hint, readable on hover, by keyboard and by touch. */
export function SetupIndicator({
  hints,
  className,
  focusable = true,
}: {
  hints: readonly SetupHint[];
  className?: string;
  focusable?: boolean;
}) {
  const t = useTranslations("setupHints");
  const reducedMotion = useReducedMotion();
  if (!hints.length) return null;
  const marker = (
    <span aria-hidden className="relative inline-flex size-2">
      <span
        className={cn(
          "absolute inset-0 rounded-full bg-amber-400/45",
          !reducedMotion && "animate-ping",
        )}
      />
      <span className="relative size-2 rounded-full bg-amber-500 dark:bg-amber-300" />
    </span>
  );
  // A tab already exposes these hints through aria-describedby. A second button
  // inside its tablist breaks the tab pattern, even with tabindex=-1.
  if (!focusable)
    return (
      <span
        aria-hidden
        className={cn(
          "pointer-events-none inline-flex size-5 items-center justify-center",
          className,
        )}
      >
        {marker}
      </span>
    );
  const description = hints.map((hint) => t(hint)).join(" ");
  const content = (
    <div className="space-y-1.5">
      <p className="font-semibold">{t("title")}</p>
      {hints.map((hint) => (
        <p key={hint}>{t(hint)}</p>
      ))}
    </div>
  );
  return (
    <TooltipProvider delayDuration={150}>
      <Popover>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <button
                type="button"
                aria-label={description}
                tabIndex={0}
                className={cn(
                  "touch:size-7 focus-visible:ring-ring inline-flex size-5 shrink-0 cursor-help items-center justify-center rounded-full outline-none focus-visible:ring-2",
                  className,
                )}
              >
                {marker}
              </button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">{content}</TooltipContent>
        </Tooltip>
        <PopoverContent
          className="w-80 max-w-[calc(100vw-2rem)] text-sm leading-relaxed"
          onOpenAutoFocus={(event) => event.preventDefault()}
        >
          {content}
        </PopoverContent>
      </Popover>
    </TooltipProvider>
  );
}
