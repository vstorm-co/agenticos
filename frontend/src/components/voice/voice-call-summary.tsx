"use client";

import { Clock, Phone, PhoneOff, WifiOff } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { LIMIT_REASONS, viewState, type CallState } from "@/lib/voice/call-reducer";
import { clock } from "@/lib/voice/clock";
import { cn } from "@/lib/utils";

import { ENDED_KEYS, type VoiceEndingCopy } from "./voice-call-strip";

/**
 * How a call that went live ended, as a card in the conversation it happened
 * in (#54): how long it ran and that its turns are saved above - or which limit
 * ended it, or that the connection dropped - and a way to call again. A call
 * that never went live says so under the composer instead.
 */
export function VoiceCallSummary({
  call,
  onCallAgain,
  endingCopy,
}: {
  call: CallState;
  onCallAgain: () => void;
  /** Which reason ended it, when not in the console's `chat.voice` words. */
  endingCopy?: VoiceEndingCopy;
}) {
  const t = useTranslations("chat.voice");
  const tEnding = endingCopy ?? t;
  if (call.phase !== "ended" || call.startedAt === null || call.failure !== null) return null;
  const view = viewState(call);
  const limit = call.endReason !== null && LIMIT_REASONS.has(call.endReason);
  const seconds = ((call.endedAt as number) - call.startedAt) / 1000;

  let title: string;
  if (view === "dropped") title = t("state.dropped");
  else if (call.endReason === "time_limit" && call.capSeconds !== null)
    title = t("view.summary.timeLimit", { minutes: Math.round(call.capSeconds / 60) });
  else if (call.endReason === null || call.endReason === "user" || !ENDED_KEYS[call.endReason])
    title = t("view.summary.ended", { duration: clock(seconds) });
  else title = tEnding(`ended.${ENDED_KEYS[call.endReason]}`);

  const minutesLeft =
    limit && call.minutesLeft !== null
      ? Math.max(0, Math.floor((call.minutesLeft * 60 - seconds) / 60))
      : null;
  const Icon = view === "dropped" ? WifiOff : limit ? Clock : PhoneOff;

  return (
    <div
      className={cn(
        "bg-card my-2.5 flex items-start gap-3 rounded-[14px] border px-3.5 py-3",
        view === "dropped" && "border-destructive/35 bg-destructive/[0.07]",
      )}
    >
      <span
        className={cn(
          "bg-muted grid h-8 w-8 shrink-0 place-items-center rounded-full",
          view === "dropped" && "text-destructive",
          limit && "text-warning",
        )}
      >
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <div className="min-w-0">
        <p className="text-[13.5px] font-semibold">{title}</p>
        <p className="text-muted-foreground mt-0.5 text-[12.5px]">
          {view === "dropped"
            ? t("failure.dropped")
            : t("view.summary.turns", { count: call.savedTurns })}
          {minutesLeft !== null && <> {t("view.summary.minutesLeft", { minutes: minutesLeft })}</>}
        </p>
        <Button type="button" variant="outline" size="sm" className="mt-2.5" onClick={onCallAgain}>
          <Phone aria-hidden />
          {limit ? t("view.summary.newCall") : t("callAgain")}
        </Button>
      </div>
    </div>
  );
}
