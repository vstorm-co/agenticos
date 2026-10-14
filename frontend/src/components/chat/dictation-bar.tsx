"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Loader2, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import type { DictationActions, DictationState } from "@/hooks/use-dictation";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { cn } from "@/lib/utils";

/** How many bars the waveform holds; the newest enters on the right. */
const BARS = 64;
/** How often the waveform takes a reading, matching the hook's level rate. */
const WAVE_EVERY_MS = 70;
/** Steps in the reduced-motion level indicator. */
const STEPS = 5;
const STEP_HEIGHTS = ["h-[5px]", "h-2", "h-[11px]", "h-3.5", "h-4"];

/** Seconds as `m:ss`, the way a recorder shows them. */
export function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

const ICON_BUTTON = "h-9 w-9 shrink-0 pointer-coarse:h-11 pointer-coarse:w-11";

/** The level over the last few seconds, scrolling left, faded at its old end. */
function Waveform({ level, flat }: { level: number; flat: boolean }) {
  const [history, setHistory] = useState<number[]>(() => Array<number>(BARS).fill(0));
  const levelRef = useRef(level);
  useEffect(() => {
    levelRef.current = level;
  });
  useEffect(() => {
    if (flat) return;
    const timer = setInterval(
      () => setHistory((previous) => [...previous.slice(1), levelRef.current]),
      WAVE_EVERY_MS,
    );
    return () => clearInterval(timer);
  }, [flat]);

  return (
    <div
      aria-hidden="true"
      data-testid="waveform"
      className="flex h-8 min-w-0 flex-1 items-center justify-end gap-0.5 overflow-hidden [mask-image:linear-gradient(90deg,transparent,#000_18%)]"
    >
      {history.map((value, index) => (
        <i
          key={index}
          className={cn(
            "bg-foreground block h-6 w-[3px] flex-none rounded-sm",
            flat ? "opacity-35" : "opacity-80",
          )}
          style={{ transform: `scaleY(${Math.max(0.12, Math.min(1, value))})` }}
        />
      ))}
    </div>
  );
}

/** Five steps lit by level: the meter when nothing may move. */
function LevelSteps({ level }: { level: number }) {
  const on = Math.round(Math.min(1, level) * STEPS);
  return (
    <span
      aria-hidden="true"
      data-testid="level-steps"
      className="flex h-4 flex-1 items-end justify-end gap-[3px]"
    >
      {STEP_HEIGHTS.map((height, index) => (
        <i
          key={height}
          data-on={index < on}
          className={cn(
            "block w-1 rounded-[1px]",
            height,
            index < on ? "bg-foreground" : "bg-border",
          )}
        />
      ))}
    </span>
  );
}

/**
 * The composer's control row while dictating: Cancel, the level, the clock and
 * Stop - and nothing else. Every hint and error goes in the strip under the box.
 *
 * While transcribing it says so, with how much audio is on its way, and keeps
 * Cancel: the request can still be abandoned. While a recording takes longer
 * than a second to upload it says how much of it has gone up instead; the
 * pulse, which says "no telling how long", is for the wait after that.
 */
export function DictationBar({
  state,
  actions,
}: {
  state: DictationState;
  actions: DictationActions;
}) {
  const t = useTranslations("chat.dictation");
  const reduced = useReducedMotion();
  const stopRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const live = state.phase === "recording";
  const transcribing = state.phase === "transcribing";

  // Where Enter and Space should land the moment there is something to stop.
  useEffect(() => {
    if (live) stopRef.current?.focus();
  }, [live]);

  // Stop is gone once it has been pressed, and focus went with it to <body>,
  // where Escape never reaches the form that cancels. Cancel is the first child
  // in both layouts, so it stays mounted: focus lands there instead.
  useEffect(() => {
    if (transcribing && document.activeElement === document.body) cancelRef.current!.focus();
  }, [transcribing]);

  if (transcribing) {
    return (
      <div className="flex items-center gap-2 pt-0.5 pb-1" aria-busy="true">
        <Button
          ref={cancelRef}
          type="button"
          variant="ghost"
          size="icon"
          onClick={actions.cancel}
          className={ICON_BUTTON}
          aria-label={t("cancelTranscription")}
          title={t("cancelTitle")}
        >
          <X className="text-muted-foreground h-4 w-4" />
        </Button>
        <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[13px]">
          {state.upload === null ? (
            <span className="font-medium motion-safe:animate-pulse">{t("transcribing")}</span>
          ) : (
            <span data-testid="dictation-upload" className="font-medium tabular-nums">
              {t("uploading", { percent: state.upload })}
            </span>
          )}
          <span className="text-muted-foreground font-mono text-xs">
            {t("ofAudio", { duration: clock(state.elapsed) })}
          </span>
        </div>
        <Button
          type="button"
          size="icon"
          disabled
          className={ICON_BUTTON}
          aria-label={t("transcribing")}
        >
          <Loader2 className="h-4 w-4 motion-safe:animate-spin" />
        </Button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 pt-0.5 pb-1">
      <Button
        ref={cancelRef}
        type="button"
        variant="ghost"
        size="icon"
        onClick={actions.cancel}
        className={ICON_BUTTON}
        aria-label={t("cancel")}
        title={t("cancelTitle")}
      >
        <X className="text-muted-foreground h-4 w-4" />
      </Button>
      {reduced ? <LevelSteps level={state.level} /> : <Waveform level={state.level} flat={!live} />}
      {/* Not live: a clock announced every second is noise. The status region
          in the composer says what matters, once. */}
      <span
        role="timer"
        aria-label={t("timerLabel")}
        className={cn(
          "inline-flex min-w-[46px] items-center gap-1.5 font-mono text-[13px] leading-none tabular-nums",
          live ? "text-foreground" : "text-muted-foreground",
        )}
      >
        {live && (
          <span
            aria-hidden="true"
            className="bg-destructive h-[7px] w-[7px] rounded-full motion-safe:animate-[pulse_1.6s_ease-in-out_infinite]"
          />
        )}
        {clock(state.elapsed)}
      </span>
      <Button
        ref={stopRef}
        type="button"
        size="icon"
        onClick={actions.stop}
        disabled={!live}
        className={ICON_BUTTON}
        aria-label={t("stop")}
        title={t("stopTitle")}
      >
        <Check className="h-4 w-4" />
      </Button>
    </div>
  );
}
