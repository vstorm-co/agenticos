"use client";

import { useTranslations } from "next-intl";

import { parsePlan } from "@/lib/plan-state";
import type { ToolCall } from "@/types";

import { PlanChecklist } from "../plan-checklist";

/**
 * What a planning call produced: the checklist, or the line it answered with.
 *
 * The generic renderer showed the *arguments* - `write_plan` is called with the
 * whole ordered list every time, so a three-step plan opened as forty lines of
 * pretty-printed JSON above a rendered copy of the same three steps. The plan is
 * the payload here, and the arguments are the plan; drawing the checklist twice in
 * two notations is drawing it once, badly.
 *
 * A granular call - one status changed, one step added - answers with a sentence
 * and no checklist, so that is what it shows.
 */
export function PlanToolResult({
  toolCall,
  resultText,
}: {
  toolCall: ToolCall;
  resultText: string;
}) {
  const t = useTranslations("chat.tools");
  const steps = parsePlan(resultText);

  if (steps === null) {
    return (
      <p className="text-foreground/80 py-1 text-[13px] leading-relaxed whitespace-pre-wrap">
        {resultText === ""
          ? toolCall.status === "error"
            ? t("toolFailed")
            : t("running")
          : resultText}
      </p>
    );
  }

  return <PlanChecklist steps={steps} className="py-1" />;
}
