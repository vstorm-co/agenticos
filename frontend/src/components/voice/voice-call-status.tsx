"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { viewState, type CallState } from "@/lib/voice/call-reducer";
import { clock } from "@/lib/voice/clock";
import type { VoiceEndReason } from "@/types/voice";

/** The ended reasons with words of their own; every other reads as a plain end. */
const ENDED_KEYS: Partial<Record<VoiceEndReason, string>> = {
  time_limit: "timeLimit",
  budget: "budget",
  minutes: "minutes",
  minutes_exhausted: "minutes",
  revoked: "revoked",
  guardrail: "guardrail",
  shutdown: "shutdown",
  voice_off: "voiceOff",
  busy: "busy",
  line_busy: "lineBusy",
  forbidden: "forbidden",
  no_agent: "forbidden",
  not_configured: "notConfigured",
  not_priced: "notPriced",
  resume_refused: "resumeRefused",
};

/** The notice frames the server sends (`pump.py`, `session.py`), by kind. */
const NOTICE_KEYS: Record<string, string> = {
  guardrail: "guardrail",
  provider_error: "providerError",
  time_limit: "timeLimit",
  budget: "budget",
  minutes: "minutes",
};

const FAILURE_KEYS = {
  mic_insecure: "micInsecure",
  mic_denied: "micDenied",
  mic_not_found: "micNotFound",
  mic_busy: "micBusy",
  connection_failed: "connectionFailed",
} as const;

/**
 * What the call is doing, how long it has run against its cap, what is left of
 * the month's minutes, and - in an assertive live region - every warning, notice
 * and reason it ended (#54). A drop or a failure offers Call again.
 */
export function VoiceCallStatus({
  call,
  now,
  agentName,
  onCallAgain,
}: {
  call: CallState;
  now: number;
  agentName: string;
  onCallAgain: () => void;
}) {
  const t = useTranslations("chat.voice");
  const view = viewState(call);
  const running = call.phase === "live" || call.phase === "reconnecting";
  const timed = running && call.startedAt !== null && call.capSeconds !== null;
  const noticeKey = call.notice === null ? undefined : NOTICE_KEYS[call.notice];

  let alert: string | null = null;
  if (call.failure !== null) alert = t(`failure.${FAILURE_KEYS[call.failure]}`);
  else if (view === "dropped") alert = t("failure.dropped");
  else if (call.phase === "ended")
    alert = t(`ended.${(call.endReason && ENDED_KEYS[call.endReason]) ?? "generic"}`);
  const canCallAgain = view === "dropped" || view === "connfailed" || view === "micblocked";

  return (
    <div className="space-y-1 text-sm">
      <p className="font-medium">{t(`state.${view}`, { agent: agentName })}</p>
      {timed && (
        <p className="text-muted-foreground font-mono text-xs tabular-nums">
          {clock((now - (call.startedAt as number)) / 1000)} / {clock(call.capSeconds as number)}
        </p>
      )}
      {call.minutesLeft !== null && (
        <p className="text-muted-foreground text-xs">
          {t("minutesLeft", { minutes: call.minutesLeft })}
        </p>
      )}
      <div role="alert" aria-live="assertive" className="text-xs empty:hidden">
        {running && call.warningSecondsLeft !== null && (
          <p>{t("notice.limitWarning", { seconds: call.warningSecondsLeft })}</p>
        )}
        {running && noticeKey && <p>{t(`notice.${noticeKey}`)}</p>}
        {alert && <p>{alert}</p>}
      </div>
      {canCallAgain && (
        <Button type="button" variant="secondary" size="sm" onClick={onCallAgain}>
          {t("callAgain")}
        </Button>
      )}
    </div>
  );
}
