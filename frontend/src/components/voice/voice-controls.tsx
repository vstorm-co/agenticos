"use client";

import { Mic, MicOff, PhoneOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";

/** Whether a key press belongs to a field somebody is typing in. */
function typing(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

interface VoiceControlsProps {
  muted: boolean;
  pushToTalk: boolean;
  disabled?: boolean;
  onMutedChange: (muted: boolean) => void;
  onPushToTalkChange: (on: boolean) => void;
  onPress: (down: boolean) => void;
  onEnd: () => void;
}

/**
 * Mute, push-to-talk and End (#54). Hands-free is the default; push-to-talk is
 * a per-person preference (`useVoiceCallStore`) and works by holding the button
 * or Space - never while focus is in a text field.
 */
export function VoiceControls({
  muted,
  pushToTalk,
  disabled,
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
      if (event.code !== "Space" || event.repeat || typing(event.target)) return;
      event.preventDefault();
      spaceHeld.current = true;
      onPress(true);
    };
    // Let go wherever focus went meanwhile - a release into a text field must
    // still close the microphone.
    const up = (event: KeyboardEvent) => {
      if (event.code !== "Space" || !spaceHeld.current) return;
      spaceHeld.current = false;
      onPress(false);
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [pushToTalk, onPress]);

  const release = () => {
    if (!held.current) return;
    held.current = false;
    onPress(false);
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        disabled={disabled}
        aria-pressed={muted}
        aria-label={muted ? t("unmute") : t("mute")}
        onClick={() => onMutedChange(!muted)}
        className="h-11 w-11"
      >
        {muted ? <MicOff className="h-5 w-5" /> : <Mic className="h-5 w-5" />}
      </Button>
      {pushToTalk && (
        <Button
          type="button"
          variant="secondary"
          disabled={disabled}
          onPointerDown={() => {
            held.current = true;
            onPress(true);
          }}
          onPointerUp={release}
          onPointerLeave={release}
          onPointerCancel={release}
          onLostPointerCapture={release}
          className="h-11 touch-none select-none"
        >
          {t("hold")}
        </Button>
      )}
      <label className="flex items-center gap-1.5 text-xs">
        <Switch
          checked={pushToTalk}
          onCheckedChange={onPushToTalkChange}
          aria-label={t("pushToTalk")}
          disabled={disabled}
        />
        {t("pushToTalk")}
      </label>
      <Button
        type="button"
        variant="destructive"
        size="icon"
        aria-label={t("end")}
        onClick={onEnd}
        className="h-11 w-11"
      >
        <PhoneOff className="h-5 w-5" />
      </Button>
    </div>
  );
}
