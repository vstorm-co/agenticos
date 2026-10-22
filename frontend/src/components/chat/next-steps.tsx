"use client";

import { ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { followUpsOf } from "@/lib/turn-extras";
import type { ChatMessage } from "@/types/chat";

/**
 * What the latest answer offered to do next (#2301), or none.
 *
 * Only when the conversation ends on that answer and it is finished: a next
 * step under an older answer is history, and one under an answer still being
 * written would be sent into a turn that has not ended.
 */
export function nextStepsOf(messages: readonly ChatMessage[], isProcessing: boolean): string[] {
  const last = messages.at(-1);
  if (isProcessing || last?.role !== "assistant" || last.isStreaming) return [];
  return followUpsOf(last.toolCalls);
}

/**
 * The next steps, as a row of buttons just above the composer: where the next
 * message is written, so a click is the message rather than a scroll back up to
 * the answer. One row, scrolled sideways when it does not fit.
 */
export function NextSteps({ steps, onPick }: { steps: string[]; onPick: (step: string) => void }) {
  const t = useTranslations("chat.extras");
  if (steps.length === 0) return null;
  return (
    <div
      role="group"
      aria-label={t("nextSteps")}
      className="flex scrollbar-none gap-1.5 overflow-x-auto px-1 pb-2"
    >
      {steps.map((step) => (
        <button
          key={step}
          type="button"
          onClick={() => onPick(step)}
          className="group bg-background border-border hover:bg-muted focus-visible:ring-ring text-foreground shadow-card inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-[13px] transition-colors outline-none focus-visible:ring-2"
        >
          {step}
          <ArrowUpRight
            className="text-muted-foreground group-hover:text-foreground h-3.5 w-3.5"
            aria-hidden
          />
        </button>
      ))}
    </div>
  );
}
