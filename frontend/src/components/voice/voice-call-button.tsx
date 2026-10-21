"use client";

import { Phone, PhoneOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";

import { Button, Popover, PopoverAnchor, PopoverContent } from "@/components/ui";
import type { VoiceReadiness, VoiceUnavailable } from "@/types/voice";

const REASON_KEYS: Record<VoiceUnavailable, string> = {
  no_voice: "noVoice",
  not_offered: "notOffered",
  no_key: "noKey",
};

const BUTTON = "h-9 w-9 shrink-0 pointer-coarse:h-11 pointer-coarse:w-11";

interface VoiceCallButtonProps {
  readiness: VoiceReadiness | null;
  /** The readiness read failed - said, rather than reading as "calls are off". */
  failed: boolean;
  disabled?: boolean;
  onStart: () => void;
  /** Whether this person may set calls up - for the organization or this agent. */
  canSetUp: boolean;
}

/**
 * The composer's call button (#54). Offered when a call would start; otherwise
 * crossed out and still focusable, saying why - the dictation rule, so a person
 * is never left guessing why this agent takes no call. Absent while the agent's
 * readiness loads, so it does not flash.
 *
 * Hover or keyboard focus opens the reason in a popover; a press toggles it,
 * because a touch screen has no hover.
 */
export function VoiceCallButton({
  readiness,
  failed,
  disabled,
  onStart,
  canSetUp,
}: VoiceCallButtonProps) {
  const t = useTranslations("chat.voice");
  const [open, setOpen] = useState(false);
  // A press focuses the button too; that focus is not a keyboard arriving.
  const pressed = useRef(false);
  const describedBy = useId();

  if (!failed && readiness === null) return null;
  if (readiness?.available) {
    return (
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={onStart}
        disabled={disabled}
        data-tour="chat-voice-call"
        aria-label={t("start")}
        title={t("start")}
        className={BUTTON}
      >
        <Phone className="text-muted-foreground h-4 w-4" />
      </Button>
    );
  }

  const reason = readiness?.unavailable;
  const key = failed || !reason ? "unchecked" : REASON_KEYS[reason];
  const title = t(`unavailable.${key}.title`);
  const body = t(`unavailable.${key}.body`);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-disabled="true"
          aria-label={t("start")}
          aria-describedby={describedBy}
          data-tour="chat-voice-call"
          className={`${BUTTON} cursor-not-allowed`}
          onPointerEnter={(event) => {
            if (event.pointerType === "mouse") setOpen(true);
          }}
          onPointerLeave={(event) => {
            if (event.pointerType === "mouse") setOpen(false);
          }}
          onPointerDown={() => {
            pressed.current = true;
          }}
          onFocus={() => {
            if (!pressed.current) setOpen(true);
            pressed.current = false;
          }}
          onBlur={() => setOpen(false)}
          onClick={() => setOpen((was) => !was)}
        >
          <PhoneOff className="text-muted-foreground h-4 w-4" />
          <span id={describedBy} className="sr-only">
            {title} {body} {canSetUp ? t("canSetUp") : null}
          </span>
        </Button>
      </PopoverAnchor>
      <PopoverContent
        side="top"
        align="end"
        className="w-[268px] text-[13px]"
        onOpenAutoFocus={(event) => event.preventDefault()}
        onCloseAutoFocus={(event) => event.preventDefault()}
      >
        <p className="font-semibold">{title}</p>
        <p className="text-muted-foreground mt-0.5">{body}</p>
        {canSetUp && <p className="text-muted-foreground mt-2">{t("canSetUp")}</p>}
      </PopoverContent>
    </Popover>
  );
}
