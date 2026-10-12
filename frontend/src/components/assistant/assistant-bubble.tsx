"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { silencePage, type BubbleKey } from "@/lib/assistant-bubbles";
import { cn } from "@/lib/utils";

interface AssistantBubbleProps {
  bubble: BubbleKey;
  /** The assistant's own name, which the bubble speaks under. */
  name: string;
  /** What the bubble's words name: the failed run, the form somebody is stuck in. */
  values: { run: string; form: string };
  /** Something waiting for the reader rather than a suggestion - shown on a phone too. */
  proactive: boolean;
  path: string;
  onAsk: (prompt: string) => void;
  /** "Not now": quiet on this page for the rest of the visit. */
  onDismiss: () => void;
  /** ×: quiet on this page from now on. */
  onSilence: () => void;
  /** Left unanswered for its moment, the bubble goes; quiet on this page for the visit. */
  onFade: () => void;
}

/** How long a bubble stays when nobody answers it; a pointer resting on it holds it. */
export const BUBBLE_VISIBLE_MS = 8000;

/**
 * The speech bubble above the AI Architect (#2063): a card that points at its
 * face, says who is speaking, and offers one thing to do (#2075).
 *
 * Its action asks the Architect; "Not now" sets it aside until the next visit;
 * × silences the page. Left alone it fades after a few seconds rather than
 * waiting on the page for an answer. On a phone only what is waiting speaks - a
 * suggestion on every page of a small screen is noise - and the × is always
 * shown there, as there is no hover to reveal it.
 */
export function AssistantBubble({
  bubble,
  name,
  values,
  proactive,
  path,
  onAsk,
  onDismiss,
  onSilence,
  onFade,
}: AssistantBubbleProps) {
  const t = useTranslations("assistantWidget");
  const [held, setHeld] = useState(false);
  // The latest callback, so a parent re-rendering does not restart the clock.
  const fade = useRef(onFade);
  useEffect(() => {
    fade.current = onFade;
  }, [onFade]);

  // Held while a pointer rests on it or focus is inside it - listened for on
  // the element rather than as props, as a status region takes no handlers.
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Set by the time an effect runs: the div is this component's only output.
    const element = root.current;
    const hold = () => setHeld(true);
    const release = () => setHeld(false);
    const events = [
      ["pointerenter", hold],
      ["pointerleave", release],
      ["focusin", hold],
      ["focusout", release],
    ] as const;
    for (const [name, listener] of events) element?.addEventListener(name, listener);
    return () => {
      for (const [name, listener] of events) element?.removeEventListener(name, listener);
    };
  }, []);

  useEffect(() => {
    if (held) return;
    const timer = setTimeout(() => fade.current(), BUBBLE_VISIBLE_MS);
    return () => clearTimeout(timer);
  }, [held]);

  return (
    <div
      ref={root}
      role="status"
      className={cn(
        "group bg-background border-border bubble-rise fixed right-4 bottom-[calc(5.25rem+env(safe-area-inset-bottom))] z-50 w-[19rem] rounded-2xl border p-3.5 shadow-[0_10px_30px_rgb(20_22_28/0.10),0_2px_6px_rgb(20_22_28/0.06)] md:right-6 md:bottom-[6.5rem]",
        !proactive && "hidden md:block",
      )}
    >
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className="font-display text-[13px] font-semibold">{name}</span>
        <button
          type="button"
          aria-label={t("silenceHere")}
          title={t("silenceHere")}
          onClick={() => {
            silencePage(path);
            onSilence();
          }}
          className="text-muted-foreground hover:text-foreground hover:bg-accent ml-auto rounded-md p-1 transition-opacity focus-visible:opacity-100 md:opacity-0 md:group-hover:opacity-100"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <p className="mb-3 text-sm leading-snug">{t(`bubbles.${bubble}.say`, values)}</p>
      <div className="flex gap-2">
        <Button size="sm" className="h-8" onClick={() => onAsk(t(`bubbles.${bubble}.ask`, values))}>
          {t(`bubbles.${bubble}.action`)}
        </Button>
        <Button size="sm" variant="outline" className="h-8" onClick={onDismiss}>
          {t("notNow")}
        </Button>
      </div>
      {/* The tail, pointing down at the face it speaks for. */}
      <span
        aria-hidden
        className="bg-background border-border absolute right-6 -bottom-[7px] h-3.5 w-3.5 rotate-45 border-r border-b"
      />
    </div>
  );
}
