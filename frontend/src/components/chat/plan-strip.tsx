"use client";

import { ChevronDown, ListChecks } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type { PlanProgress } from "@/lib/plan-state";
import { cn } from "@/lib/utils";

import { PlanChecklist, PlanMeter } from "./plan-checklist";

/**
 * The plan the agent is working to, above the composer.
 *
 * Where it has to be: the plan is written in one turn and worked through over the
 * next several, so in the transcript it is a step scrolled off the top by the work
 * it describes. Reading "what is it doing, and how much is left" meant scrolling
 * back for a checklist that was already stale. In the dock it stays put and stays
 * current - the fold in `lib/plan-state.ts` folds every planning call, so a status
 * change three turns later moves this bar.
 *
 * Open while there is work in flight and closed once every step is settled, until
 * somebody says otherwise - a finished plan is a receipt, and a receipt does not
 * need to hold six lines of the composer's height. `null` is "nobody has decided",
 * which is what lets the default follow the plan rather than being frozen at mount.
 */
export function PlanStrip({ plan }: { plan: PlanProgress | null }) {
  const t = useTranslations("chat.plan");
  const [choice, setChoice] = useState<boolean | null>(null);

  if (plan === null) return null;

  const open = choice ?? !plan.finished;
  const headline = plan.active?.content ?? (plan.finished ? t("allDone") : t("heading"));

  return (
    <div
      data-tour="chat-plan"
      className="glass border-foreground/8 mb-2 overflow-hidden rounded-xl border"
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setChoice(!open)}
        className="hover:bg-foreground/[0.03] flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors"
      >
        <ListChecks className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
        <span className="text-foreground/85 min-w-0 flex-1 truncate text-[13px]">{headline}</span>
        <PlanMeter completed={plan.completed} total={plan.total} percent={plan.percent} />
        <ChevronDown
          className={cn(
            "text-muted-foreground h-3.5 w-3.5 shrink-0 transition-transform duration-200",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <div className="border-foreground/8 max-h-56 scrollbar-thin overflow-y-auto border-t px-3 py-2.5">
          <PlanChecklist steps={plan.steps} />
        </div>
      )}
    </div>
  );
}
