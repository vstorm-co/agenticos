"use client";

import { useTranslations } from "next-intl";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { DictationStrip } from "@/components/chat/dictation-strip";
import { useAudioLevel } from "@/hooks/use-audio-level";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import type { VoiceSession } from "@/hooks/use-voice-session";
import { cn } from "@/lib/utils";
import { viewState } from "@/lib/voice/call-reducer";
import { waveVisual } from "@/lib/voice/waveform";
import { useVoiceCallStore, useVoiceGlowStore } from "@/stores";

import { voiceCallHint, type VoiceEndingCopy } from "./voice-call-strip";
import { VoiceCallStatus } from "./voice-call-status";
import { VoiceControls } from "./voice-controls";
import { VoiceLevelMeter } from "./voice-level-meter";
import { VoiceWaveform } from "./voice-waveform";

/** Whether a call is on - connecting, live or reconnecting - so the bar stands in for the composer. */
export function callActive(session: VoiceSession): boolean {
  const { phase } = session.call;
  return phase === "connecting" || phase === "live" || phase === "reconnecting";
}

/** The page's clock, a tick a second while `running`: the call's timer and countdowns. */
export function useSecondClock(running: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const tick = () => setNow(Date.now());
    // At once, too: the clock held still while nothing was counting.
    const first = window.setTimeout(tick, 0);
    const timer = window.setInterval(tick, 1000);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(timer);
    };
  }, [running]);
  return now;
}

/** What the call's strip says right now, for whoever draws the strip under the call. */
export function useVoiceCallHint({
  session,
  canDecide,
  onShowApproval,
  endingCopy,
  active,
}: {
  session: VoiceSession;
  canDecide: boolean;
  onShowApproval: () => void;
  endingCopy?: VoiceEndingCopy;
  /** Whether a call is on; off, nothing is said and the clock does not tick. */
  active: boolean;
}) {
  const tVoice = useTranslations("chat.voice");
  const tView = useTranslations("chat.voice.view");
  const tTools = useTranslations("chat.tools");
  const now = useSecondClock(active);
  const pushToTalk = useVoiceCallStore((state) => state.pushToTalk);
  if (!active) return null;
  return voiceCallHint(
    {
      call: session.call,
      now,
      pushToTalk,
      tTools,
      tEnding: endingCopy ?? tVoice,
      onShowApproval: canDecide ? onShowApproval : null,
    },
    tView,
  );
}

/**
 * The call bar while a call is on (#54): what the call is doing and its time, a
 * waveform of both voices drawn from their real levels in the theme's ink, and
 * push to talk, Mute and End. Focus moves here when the call starts; Escape does
 * nothing, because only End ends a call.
 *
 * `pill` is the console's `/chat`: one dark pill floating above a composer that
 * does not change at all - the agent's face, what the call is doing, its time,
 * a small wave and the controls - and the composer draws the strip from
 * `useVoiceCallHint`. Otherwise - a hosted page - the bar is a panel of its own
 * with its glow and its strip.
 *
 * Under reduced motion there is no canvas and no glow: a stepped meter and the
 * label carry the state.
 */
export function VoiceCallBar({
  session,
  agentName,
  canDecide,
  onShowApproval,
  endingCopy,
  pill = false,
  avatar,
}: {
  session: VoiceSession;
  agentName: string;
  /** Whether the person on the call may decide an approval - otherwise nothing points at buttons they lack. */
  canDecide: boolean;
  onShowApproval: () => void;
  /** How a limit ending the call and its notices are put, when not the console's `chat.voice`. */
  endingCopy?: VoiceEndingCopy;
  pill?: boolean;
  /** The agent's face, at the pill's start. */
  avatar?: ReactNode;
}) {
  const tView = useTranslations("chat.voice.view");
  const { call, pressToTalk, setMuted, end } = session;
  const now = useSecondClock(true);
  const { pushToTalk, setPushToTalk } = useVoiceCallStore();
  const glowStyle = useVoiceGlowStore((state) => state.style);
  const reduced = useReducedMotion();
  const input = useAudioLevel(session.localStream);
  const output = useAudioLevel(session.remoteStream);
  const [holding, setHolding] = useState(false);
  const press = useCallback(
    (down: boolean) => {
      setHolding(down);
      pressToTalk(down);
    },
    [pressToTalk],
  );

  const barRef = useRef<HTMLDivElement>(null);
  useEffect(() => barRef.current?.focus(), []);
  const audioRef = useRef<HTMLAudioElement>(null);
  useEffect(() => {
    (audioRef.current as HTMLAudioElement).srcObject = session.remoteStream;
  }, [session.remoteStream]);

  const view = viewState(call);
  const visual = waveVisual(view, !call.muted && (!pushToTalk || holding));
  const agentSide = visual === "agent";
  const working = visual === "thinking" || visual === "tool" ? visual : undefined;
  const quiet = visual === "quiet" || visual === "connecting" || visual === "approval";
  const hint = useVoiceCallHint({
    session,
    canDecide,
    onShowApproval,
    endingCopy,
    active: !pill,
  });
  // Hold to talk replaces Mute, so turning it on unmutes: a held microphone
  // that stays closed would say "talking" to nobody.
  const changePushToTalk = useCallback(
    (on: boolean) => {
      if (on && call.muted) setMuted(false);
      setPushToTalk(on);
    },
    [call.muted, setMuted, setPushToTalk],
  );
  const who = agentSide ? agentName : call.muted ? tView("micOff") : tView("you");

  return (
    <div className="relative isolate">
      {/* The agent's voice. Never with controls: End is the only control a call has. */}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption -- the captions are the call's own, drawn live in the conversation and announced by its polite region; a live WebRTC stream has no track file to attach. */}
      <audio ref={audioRef} autoPlay data-testid="voice-call-audio" />
      {!pill && !reduced && glowStyle !== "off" && (
        <div
          aria-hidden
          data-testid="voice-call-glow"
          className="voice-call-glow"
          data-side={agentSide && glowStyle === "vivid" ? "agent" : "caller"}
          data-working={working}
          data-quiet={quiet ? "" : undefined}
          style={{ "--voice-level": Math.max(input, output).toFixed(3) } as CSSProperties}
        />
      )}
      {pill ? (
        <div
          ref={barRef}
          role="group"
          aria-label={tView("bar")}
          tabIndex={-1}
          className={cn(
            "bg-foreground text-background motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-2 flex items-center gap-2 rounded-full py-1.5 pr-1.5 pl-1.5 shadow-lg outline-none",
            call.approval !== null && "ring-warning ring-2",
          )}
        >
          {avatar && (
            <span className="ring-background/20 shrink-0 rounded-full ring-2">{avatar}</span>
          )}
          <VoiceCallStatus
            call={call}
            now={now}
            agentName={agentName}
            pushToTalk={pushToTalk}
            holding={holding}
            endingCopy={endingCopy}
            compact
          />
          {!reduced && (
            <span className="w-14 shrink-0 @md:w-20">
              <VoiceWaveform visual={visual} levels={{ input, output }} compact />
            </span>
          )}
          <VoiceControls
            muted={call.muted}
            pushToTalk={pushToTalk}
            holding={holding}
            onMutedChange={setMuted}
            onPushToTalkChange={changePushToTalk}
            onPress={press}
            onEnd={end}
            inverse
          />
        </div>
      ) : (
        <>
          <div
            ref={barRef}
            role="group"
            aria-label={tView("bar")}
            tabIndex={-1}
            className={cn(
              "panel relative rounded-[18px] py-2.5 pr-2 pl-3 transition-colors outline-none @xl:pr-2.5 @xl:pl-4",
              hint !== null && "rounded-b-none",
              call.approval !== null && "border-warning/55",
            )}
          >
            <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1 [grid-template-areas:'status_ctrls'_'vis_vis'] @xl:grid-cols-[minmax(170px,auto)_minmax(0,1fr)_auto] @xl:gap-x-3.5 @xl:[grid-template-areas:'status_vis_ctrls']">
              <div className="min-w-0 [grid-area:status]">
                <VoiceCallStatus
                  call={call}
                  now={now}
                  agentName={agentName}
                  pushToTalk={pushToTalk}
                  holding={holding}
                  endingCopy={endingCopy}
                />
              </div>
              <div className="flex min-w-0 items-center [grid-area:vis]">
                {reduced ? (
                  <div className="text-muted-foreground flex items-center gap-2 text-xs">
                    <VoiceLevelMeter
                      level={agentSide ? output : input}
                      label={who}
                      tone={agentSide ? "agent" : "caller"}
                    />
                    <span aria-hidden>{who}</span>
                  </div>
                ) : (
                  <VoiceWaveform visual={visual} levels={{ input, output }} />
                )}
              </div>
              <div className="[grid-area:ctrls]">
                <VoiceControls
                  muted={call.muted}
                  pushToTalk={pushToTalk}
                  holding={holding}
                  onMutedChange={setMuted}
                  onPushToTalkChange={changePushToTalk}
                  onPress={press}
                  onEnd={end}
                />
              </div>
            </div>
            {!reduced && (
              <div
                aria-hidden
                className="voice-call-edge"
                style={{ opacity: agentSide ? output * 0.9 : 0 }}
              />
            )}
          </div>
          <DictationStrip hint={hint} />
        </>
      )}
    </div>
  );
}
