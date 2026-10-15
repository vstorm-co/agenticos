"use client";

import { Hand, Mic, MicOff, PhoneOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** The controls Space already means something to - pressing a button, typing in a field. */
const SPACE_OWNERS =
  "input,textarea,select,button,a,summary,[role=button],[role=switch],[role=checkbox]";

/**
 * Whether Space belongs to whatever has focus rather than to push to talk: a
 * field somebody is typing in, or a control Space presses. Hold to talk and the
 * push-to-talk toggle are the exceptions: Space on the first is what it is for,
 * and the second keeps focus after the click that turned push to talk on, so
 * Space there would otherwise turn it off again instead of talking.
 */
function ownsSpace(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const control = target.closest(SPACE_OWNERS);
  return control !== null && !control.hasAttribute("data-voice-hold");
}

interface VoiceControlsProps {
  muted: boolean;
  pushToTalk: boolean;
  /** Whether the microphone is held open right now, by the button or by Space. */
  holding: boolean;
  onMutedChange: (muted: boolean) => void;
  onPushToTalkChange: (on: boolean) => void;
  onPress: (down: boolean) => void;
  onEnd: () => void;
}

const ICON = "h-9 w-9 shrink-0 pointer-coarse:h-11 pointer-coarse:w-11";

/**
 * The call bar's controls (#54): push to talk, then Mute - or, with push to
 * talk on, Hold to talk - then End. Hands-free is the default; push to talk is
 * a per-person preference (`useVoiceCallStore`) and works by holding the button
 * or Space, never while focus is in a text field. Only End ends a call.
 */
export function VoiceControls({
  muted,
  pushToTalk,
  holding,
  onMutedChange,
  onPushToTalkChange,
  onPress,
  onEnd,
}: VoiceControlsProps) {
  const t = useTranslations("chat.voice.controls");
  // Held by the pointer, and by Space: each lets go once, whatever happens in between.
  const held = useRef(false);
  const spaceHeld = useRef(false);

  useEffect(() => {
    if (!pushToTalk) return;
    const down = (event: KeyboardEvent) => {
      if (event.code !== "Space" || ownsSpace(event.target)) return;
      // Cancelled before the repeat check: a held key repeats, and each repeat
      // left alone scrolls the page.
      event.preventDefault();
      if (event.repeat) return;
      spaceHeld.current = true;
      onPress(true);
    };
    // Let go wherever focus went meanwhile - a release into a text field must
    // still close the microphone.
    const up = (event: KeyboardEvent) => {
      if (event.code !== "Space" || !spaceHeld.current) return;
      // A button is pressed on Space's keyup; this one was talking, not pressing.
      event.preventDefault();
      spaceHeld.current = false;
      onPress(false);
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      // Push to talk switched off, or the call over, with the microphone held:
      // let go, so it does not stay open with nothing left to release it.
      if (spaceHeld.current || held.current) {
        spaceHeld.current = false;
        held.current = false;
        onPress(false);
      }
    };
  }, [pushToTalk, onPress]);

  const release = () => {
    if (!held.current) return;
    held.current = false;
    onPress(false);
  };

  return (
    <div className="flex shrink-0 items-center gap-0.5 @xl:gap-1.5">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-pressed={pushToTalk}
        data-voice-hold
        aria-label={t("pushToTalk")}
        title={t("pushToTalk")}
        onClick={() => onPushToTalkChange(!pushToTalk)}
        className={cn(ICON, pushToTalk && "bg-foreground text-background hover:bg-foreground/90")}
      >
        <Hand className="h-4 w-4" />
      </Button>
      {pushToTalk ? (
        <Button
          type="button"
          variant="outline"
          aria-pressed={holding}
          data-voice-hold
          onPointerDown={() => {
            held.current = true;
            onPress(true);
          }}
          onPointerUp={release}
          onPointerLeave={release}
          onPointerCancel={release}
          onLostPointerCapture={release}
          className={cn(
            "h-9 touch-none gap-2 px-3 select-none pointer-coarse:h-11",
            holding && "bg-foreground text-background hover:bg-foreground motion-safe:scale-[0.97]",
          )}
        >
          <Mic className="h-4 w-4" aria-hidden />
          <span className="sr-only @xl:not-sr-only">{t("hold")}</span>
          <kbd
            aria-hidden
            className="hidden rounded border border-b-2 border-current/30 px-1 font-mono text-[10.5px] @xl:inline"
          >
            {/* i18n-exempt: the name printed on the key itself. */}
            Space
          </kbd>
        </Button>
      ) : (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-pressed={muted}
          aria-label={muted ? t("unmute") : t("mute")}
          title={muted ? t("unmute") : t("mute")}
          onClick={() => onMutedChange(!muted)}
          className={cn(ICON, muted && "bg-foreground text-background hover:bg-foreground/90")}
        >
          {muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
        </Button>
      )}
      <Button
        type="button"
        variant="destructive"
        aria-label={t("end")}
        onClick={onEnd}
        className="h-9 w-9 gap-1.5 px-0 @xl:w-auto @xl:px-4 pointer-coarse:h-11 pointer-coarse:w-11"
      >
        <PhoneOff className="h-4 w-4" aria-hidden />
        <span className="hidden @xl:inline">{t("endShort")}</span>
      </Button>
    </div>
  );
}
