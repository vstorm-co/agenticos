"use client";

import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import type { VoiceEndingCopy } from "./voice-call-strip";

import { toolCaption, toolDisplayName } from "@/lib/agent-step-captions";
import { viewState, type CallState } from "@/lib/voice/call-reducer";
import { clock } from "@/lib/voice/clock";
import { cn } from "@/lib/utils";

/** The notices that mean a limit is ending the call, by kind (`session.py`). */
export const ENDING_NOTICES: Record<string, string> = {
  time_limit: "timeLimit",
  budget: "budget",
  unavailable: "unavailable",
};

/** The notices with words of their own; any other is left unsaid. */
const NOTICE_KEYS: Record<string, string> = {
  ...ENDING_NOTICES,
  guardrail: "guardrail",
  provider_error: "providerError",
};

/** The states whose label shimmers: waiting on something with no level to show. */
const WORKING = new Set(["connecting", "reconnecting", "thinking", "tool"]);

/**
 * The call bar's status (#54): what the call is doing, its time against its
 * cap and the month's minutes left - and, for screen readers, an assertive
 * region with the approval waiting, the one-minute warning and every notice.
 */
export function VoiceCallStatus({
  call,
  now,
  agentName,
  pushToTalk,
  holding,
  endingCopy,
}: {
  call: CallState;
  now: number;
  agentName: string;
  pushToTalk: boolean;
  holding: boolean;
  /** How a call's end and its notices are put, when not the console's `chat.voice`. */
  endingCopy?: VoiceEndingCopy;
}) {
  const t = useTranslations("chat.voice");
  const tTools = useTranslations("chat.tools");
  const tEnding = endingCopy ?? t;
  const view = viewState(call);
  const ending = call.notice === null ? undefined : ENDING_NOTICES[call.notice];
  const noticeKey = call.notice === null ? undefined : NOTICE_KEYS[call.notice];

  let label: string;
  if (ending) label = tEnding(`view.ending.${ending}`);
  else if (view === "listening" || view === "limitwarn") {
    if (holding && !call.muted) label = t("view.talking");
    else if (call.muted) label = t("view.muted");
    else if (pushToTalk) label = t("controls.hold");
    else label = t("state.listening");
  } else if (view === "tool" && call.tool !== null) label = toolCaption(call.tool, tTools);
  else label = t(`state.${view}`, { agent: agentName });

  const timed = call.startedAt !== null && call.capSeconds !== null;
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <p className="flex min-w-0 items-center gap-1.5 text-sm font-semibold">
        {(view === "connecting" || view === "reconnecting") && (
          <Loader2
            data-testid="voice-call-connecting"
            className="text-muted-foreground h-3.5 w-3.5 shrink-0 motion-safe:animate-spin"
            aria-hidden
          />
        )}
        <span className={cn("truncate", WORKING.has(view) && !ending && "voice-call-shimmer")}>
          {label}
        </span>
      </p>
      <p className="text-muted-foreground truncate text-xs">
        {!timed ? (
          t("view.settingUp")
        ) : (
          <>
            <span className="text-foreground font-mono tabular-nums">
              {clock((now - (call.startedAt as number)) / 1000)}
            </span>
            <span
              className={cn(
                "font-mono tabular-nums",
                call.warningSecondsLeft !== null && "text-warning font-semibold",
              )}
            >
              {" / "}
              {clock(call.capSeconds as number)}
            </span>
            {view === "tool" && call.tool !== null ? (
              <span className="font-mono"> · {call.tool}</span>
            ) : null}
          </>
        )}
      </p>
      <div role="alert" aria-live="assertive" className="sr-only">
        {call.approval && (
          <p>
            {t("view.announceApproval", {
              tool: toolDisplayName(call.approval.tool, tTools),
              seconds: call.approval.timeoutSeconds,
            })}
          </p>
        )}
        {call.warningSecondsLeft !== null && (
          <p>{tEnding("notice.limitWarning", { seconds: call.warningSecondsLeft })}</p>
        )}
        {noticeKey && <p>{tEnding(`notice.${noticeKey}`)}</p>}
      </div>
    </div>
  );
}
