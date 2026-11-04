"use client";

import { AlertTriangle, CircleDashed } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui";

/** How many problems the quick view spells out before it only counts the rest. */
const SHOWN = 3;

/**
 * A step's warning sign on its card: hovering it says what the first few problems
 * are, and a click opens the step, whose dialog lists every one of them.
 */
export function ProblemBadge({
  problems,
  onOpen,
  revealed = false,
}: {
  /** The step's problems, each already a sentence naming its field. */
  problems: readonly string[];
  onOpen: () => void;
  /** A failed test or publish makes incomplete setup a visible error. */
  revealed?: boolean;
}) {
  const t = useTranslations("workflows");
  const more = problems.length - SHOWN;
  return (
    // Its own provider: a card renders on the canvas and in previews alike.
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={t(revealed ? "panelWarningCount" : "toolbarSetup", {
              count: problems.length,
            })}
            onClick={(event) => {
              // The step opens; xyflow does not also take the click as a selection.
              event.stopPropagation();
              onOpen();
            }}
            className={cn(
              "focus-visible:ring-ring rounded outline-none focus-visible:ring-2",
              revealed ? "text-destructive" : "text-muted-foreground",
            )}
          >
            {revealed ? (
              <AlertTriangle aria-hidden="true" className="size-3.5" />
            ) : (
              <CircleDashed aria-hidden="true" className="size-3.5" />
            )}
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs space-y-1.5 py-2">
          <ul className="space-y-1">
            {problems.slice(0, SHOWN).map((problem, index) => (
              <li key={index} className="flex items-start gap-1.5">
                <AlertTriangle aria-hidden="true" className="mt-0.5 size-3 shrink-0" />
                {problem}
              </li>
            ))}
          </ul>
          <p className="border-background/20 border-t pt-1.5 opacity-70">
            {more > 0 ? t("problemBadgeMore", { count: more }) : t("problemBadgeOpen")}
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
