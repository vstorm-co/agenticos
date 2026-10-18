"use client";

import { useId, useRef, useState } from "react";
import { MicOff } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Popover, PopoverAnchor, PopoverContent } from "@/components/ui";

import type { DictationUnavailable as Why } from "./dictation-strip";

interface DictationUnavailableProps {
  why: Why;
  /** Whether this person may set dictation up - for the organization or this agent. */
  canSetUp: boolean;
  /** Opens or closes the same explanation in the strip under the composer. */
  onExplain: () => void;
}

/**
 * The crossed-out microphone: dictation is on for this organization, and cannot
 * run from here yet.
 *
 * `aria-disabled` rather than `disabled`, so it stays focusable and can say why.
 * Hovering with a mouse or reaching it from the keyboard opens a popover; a
 * click or a tap opens the explanation in the strip under the composer instead,
 * because a touch screen has no hover and a popover there is one more thing to
 * close.
 *
 * The popover holds no links: it closes when the pointer leaves the button or
 * focus leaves it, so nothing in it can be reached. Where to set dictation up
 * is in the strip a press opens, and the popover says so.
 */
export function DictationUnavailable({ why, canSetUp, onExplain }: DictationUnavailableProps) {
  const t = useTranslations("chat.dictation");
  const tInput = useTranslations("chat.input");
  const [open, setOpen] = useState(false);
  // A press focuses the button too; that focus is not a keyboard arriving.
  const pressed = useRef(false);
  const describedBy = useId();

  const title =
    why === "no_agent"
      ? t("hint.noAgentTitle")
      : why === "no_key"
        ? t("hint.noKeyTitle")
        : why === "unchecked"
          ? t("hint.uncheckedTitle")
          : t("hint.notSetUpTitle");
  const body =
    why === "no_agent"
      ? t("hint.noAgentBody")
      : why === "no_key"
        ? t("hint.noKeyBody")
        : why === "unchecked"
          ? t("hint.uncheckedBody")
          : t("hint.notSetUpBody");

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-disabled="true"
          aria-label={tInput("voiceInput")}
          aria-describedby={describedBy}
          className="h-9 w-9 shrink-0 cursor-not-allowed pointer-coarse:h-11 pointer-coarse:w-11"
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
          onClick={() => {
            setOpen(false);
            onExplain();
          }}
        >
          <MicOff className="text-muted-foreground h-4 w-4" />
          <span id={describedBy} className="sr-only">
            {title} {body}
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
        {why !== "no_agent" && why !== "unchecked" && (
          <p className="text-muted-foreground mt-2">
            {canSetUp ? t("pressToSetUp") : t("askAdmin")}
          </p>
        )}
      </PopoverContent>
    </Popover>
  );
}
