"use client";

import { AudioLines, AudioLinesOff } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import { Button, Popover, PopoverAnchor, PopoverContent } from "@/components/ui";
import { cn } from "@/lib/utils";
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
  /** The agent's Voice card in the Builder, for whoever may edit it; null for everyone else. */
  setUpHref: string | null;
  /** Standing in Send's place, so drawn like it (#2301). */
  prominent?: boolean;
  /** Beside a draft being tested, which a call does not run: the button says so. */
  publishedOnly?: boolean;
}

/** How long the reason stays open after the pointer leaves, so it can reach the link. */
const CLOSE_DELAY_MS = 200;

/**
 * The composer's call button (#54). Offered when a call would start; otherwise
 * crossed out and still focusable, saying why - the dictation rule, so a person
 * is never left guessing why this agent takes no call. Absent while the agent's
 * readiness loads, so it does not flash. An agent with no voice set up shows
 * it too: every agent can be called once it has a voice, and the reason says
 * where that is set - the agent's Voice card in the Builder.
 *
 * Hover or keyboard focus opens the reason in a popover; a press toggles it,
 * because a touch screen has no hover. The pointer may cross into the popover
 * to follow its link.
 */
export function VoiceCallButton({
  readiness,
  failed,
  disabled,
  onStart,
  setUpHref,
  prominent = false,
  publishedOnly = false,
}: VoiceCallButtonProps) {
  const t = useTranslations("chat.voice");
  const [open, setOpen] = useState(false);
  // A press focuses the button too; that focus is not a keyboard arriving.
  const pressed = useRef(false);
  const describedBy = useId();
  const closing = useRef<number | null>(null);
  const content = useRef<HTMLDivElement>(null);
  const link = useRef<HTMLAnchorElement>(null);
  const keepOpen = () => {
    if (closing.current !== null) window.clearTimeout(closing.current);
    closing.current = null;
  };
  const closeSoon = () => {
    keepOpen();
    closing.current = window.setTimeout(() => setOpen(false), CLOSE_DELAY_MS);
  };
  useEffect(() => keepOpen, []);

  if (!failed && readiness === null) return null;
  if (readiness?.available) {
    return (
      <Button
        type="button"
        variant={prominent ? "default" : "ghost"}
        size="icon"
        onClick={onStart}
        disabled={disabled}
        data-tour="chat-voice-call"
        aria-label={t("start")}
        title={publishedOnly ? t("startPublished") : t("start")}
        className={cn(BUTTON, prominent && "transition-transform active:scale-90")}
      >
        <AudioLines className={prominent ? "h-4 w-4" : "text-muted-foreground h-4 w-4"} />
      </Button>
    );
  }

  const reason = readiness?.unavailable;
  const key = failed || !reason ? "unchecked" : REASON_KEYS[reason];
  const setUp = !failed && reason ? setUpHref : null;
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
            if (event.pointerType !== "mouse") return;
            keepOpen();
            setOpen(true);
          }}
          onPointerLeave={(event) => {
            if (event.pointerType === "mouse") closeSoon();
          }}
          onPointerDown={() => {
            pressed.current = true;
          }}
          onFocus={() => {
            if (!pressed.current) setOpen(true);
            pressed.current = false;
          }}
          onBlur={(event) => {
            if (!content.current?.contains(event.relatedTarget)) setOpen(false);
          }}
          // A press opens it and hands focus to the link, so a keyboard reaches it too.
          onClick={() => {
            setOpen(true);
            window.requestAnimationFrame(() => link.current?.focus());
          }}
        >
          <AudioLinesOff className="text-muted-foreground h-4 w-4" />
          <span id={describedBy} className="sr-only">
            {title} {body}
          </span>
        </Button>
      </PopoverAnchor>
      <PopoverContent
        ref={content}
        side="top"
        align="end"
        className="w-[268px] text-[13px]"
        onOpenAutoFocus={(event) => event.preventDefault()}
        onCloseAutoFocus={(event) => event.preventDefault()}
        onPointerEnter={keepOpen}
        onPointerLeave={(event) => {
          if (event.pointerType === "mouse") closeSoon();
        }}
      >
        <p className="font-semibold">{title}</p>
        <p className="text-muted-foreground mt-0.5">{body}</p>
        {setUp !== null ? (
          <Link
            ref={link}
            href={setUp}
            className="text-foreground mt-2 inline-block font-medium underline underline-offset-[3px]"
          >
            {t("openBuilder")}
          </Link>
        ) : (
          !failed && reason && <p className="text-muted-foreground mt-2">{t("askEditor")}</p>
        )}
      </PopoverContent>
    </Popover>
  );
}
