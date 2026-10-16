"use client";

import type { ReactNode } from "react";
import { Clock, Hand, Lock, MicOff, PhoneOff, ShieldAlert, WifiOff } from "lucide-react";
import type { useTranslations } from "next-intl";

import type { StripHint } from "@/components/chat/dictation-strip";
import { Button } from "@/components/ui/button";
import { toolDisplayName } from "@/lib/agent-step-captions";
import { viewState, type CallState } from "@/lib/voice/call-reducer";
import { clock } from "@/lib/voice/clock";
import type { VoiceEndReason } from "@/types/voice";

import { ENDING_NOTICES } from "./voice-call-status";

type Translate = ReturnType<typeof useTranslations>;

/**
 * The words for how a call ends, rooted where `chat.voice` is: the summary's
 * title (`ended.*`), the bar's ending label (`view.ending.*`) and strip
 * (`view.strip.ending.*`), and the notices it announces (`notice.*`). The
 * console's own are `chat.voice`; the hosted page passes `hosted.voice`, which
 * holds those keys in a visitor's words - no budget, no access, no guardrail.
 */
export type VoiceEndingCopy = Translate;

const strong = (chunks: ReactNode) => (
  <strong className="text-foreground font-semibold">{chunks}</strong>
);
const kbd = (chunks: ReactNode) => (
  <kbd className="border-border bg-card text-foreground rounded border border-b-2 px-1 font-mono text-[11px]">
    {chunks}
  </kbd>
);

function StripAction({
  primary = false,
  onClick,
  children,
}: {
  primary?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant={primary ? "default" : "outline"}
      onClick={onClick}
      className="h-7 px-2.5 text-xs pointer-coarse:h-11"
    >
      {children}
    </Button>
  );
}

/**
 * What the strip under the call bar says (#54): whatever needs the person -
 * the microphone prompt, an approval waiting above (with a way back to it), an
 * approval they cannot give, the minute left, a limit ending the call - and,
 * when nothing does, how push to talk works. `t` is `chat.voice.view`.
 */
export function voiceCallHint(
  input: {
    call: CallState;
    now: number;
    pushToTalk: boolean;
    tTools: Translate;
    /** How a limit ending the call is put: `chat.voice`, or the page's own ({@link VoiceEndingCopy}). */
    tEnding: VoiceEndingCopy;
    /** Brings the card into view; null when the person cannot decide it anyway. */
    onShowApproval: (() => void) | null;
  },
  t: Translate,
): StripHint | null {
  const { call, now, pushToTalk } = input;
  const view = viewState(call);
  const ending = call.notice === null ? undefined : ENDING_NOTICES[call.notice];
  if (call.phase === "connecting") {
    return { key: "mic", tone: "hint", icon: Lock, message: t.rich("strip.allowMic", { strong }) };
  }
  if (view === "reconnecting") {
    return {
      key: "reconnecting",
      tone: "warn",
      icon: WifiOff,
      message: t.rich("strip.reconnecting", { strong }),
    };
  }
  if (call.approval !== null) {
    const left = Math.max(0, Math.ceil((call.approval.deadline - now) / 1000));
    return {
      key: "approval",
      tone: "warn",
      icon: ShieldAlert,
      // The card announces itself; the strip only points to it.
      quiet: true,
      message: t.rich("strip.approval", { strong, time: clock(left) }),
      actions: input.onShowApproval && (
        <StripAction onClick={input.onShowApproval}>{t("strip.showCard")}</StripAction>
      ),
    };
  }
  if (call.approvalUnavailable !== null) {
    return {
      key: "noapproval",
      tone: "hint",
      icon: Lock,
      message: t.rich("strip.noApproval", {
        strong,
        tool: toolDisplayName(call.approvalUnavailable.tool, input.tTools),
      }),
    };
  }
  if (ending) {
    return {
      key: "ending",
      tone: "warn",
      icon: Clock,
      message: input.tEnding.rich(`view.strip.ending.${ending}`, { strong }),
    };
  }
  if (call.warningSecondsLeft !== null && call.warningAt !== null) {
    const since = (now - call.warningAt) / 1000;
    return {
      key: "limitwarn",
      tone: "warn",
      icon: Clock,
      quiet: true,
      message: t.rich("strip.limitWarning", {
        strong,
        remaining: clock(call.warningSecondsLeft - since),
        limit: clock(call.capSeconds as number),
      }),
    };
  }
  if (pushToTalk) {
    return {
      key: "ptt",
      tone: "hint",
      icon: Hand,
      message: t.rich("strip.pushToTalk", { strong, kbd }),
    };
  }
  return null;
}

const FAILURE_KEYS = {
  mic_insecure: "micInsecure",
  mic_denied: "micDenied",
  mic_not_found: "micNotFound",
  mic_busy: "micBusy",
  connection_failed: "connectionFailed",
} as const;

/** The reasons a call is refused at setup, or ended, with words of their own. */
export const ENDED_KEYS: Partial<Record<VoiceEndReason, string>> = {
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

/**
 * Why a call never got going - the microphone, the connection, or the server
 * refusing it - for the strip under the composer once it is back (#54). Null for
 * a call that went live, whose end the conversation's summary card tells, and
 * for one the person hung up on before it started. `t` is `chat.voice`, or
 * `hosted.voice` on the hosted page, which holds the same keys in a visitor's words.
 */
export function voiceFailureHint(
  input: { call: CallState; onRetry: () => void; onDismiss: () => void },
  t: Translate,
): StripHint | null {
  const { call } = input;
  let message: ReactNode;
  if (call.failure === "connection_failed" && call.startedAt !== null)
    // It went live, then the audio could not get through.
    message = t.rich("view.mediaFailed", { strong });
  else if (call.failure !== null)
    message = t.rich(`failure.${FAILURE_KEYS[call.failure]}`, { strong });
  else if (call.phase === "ended" && call.startedAt === null && call.endReason !== "user")
    message = t.rich("view.refused", {
      strong,
      reason: t(`ended.${(call.endReason && ENDED_KEYS[call.endReason]) ?? "generic"}`),
    });
  else return null;
  return {
    key: `failure-${call.failure ?? call.endReason}`,
    tone: "error",
    icon:
      call.failure === "connection_failed" ? WifiOff : call.failure === null ? PhoneOff : MicOff,
    message,
    actions: (
      <>
        <StripAction primary onClick={input.onRetry}>
          {t("view.tryAgain")}
        </StripAction>
        <StripAction onClick={input.onDismiss}>{t("view.dismiss")}</StripAction>
      </>
    ),
  };
}
