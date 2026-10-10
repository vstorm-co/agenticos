"use client";

import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { silencePage, type BubbleKey } from "@/lib/assistant-bubbles";
import { cn } from "@/lib/utils";

interface AssistantBubbleProps {
  bubble: BubbleKey;
  /** What the bubble's words name: the failed run, the form somebody is stuck in. */
  values: { run: string; form: string };
  /** Something waiting for the reader rather than a suggestion - shown on a phone too. */
  proactive: boolean;
  path: string;
  onAsk: (prompt: string) => void;
  onSilence: () => void;
}

/**
 * The speech bubble above the AI Architect (#2063): one line, a click asks it,
 * × silences this page. On a phone only what is waiting speaks - a suggestion
 * on every page of a small screen is noise.
 */
export function AssistantBubble({
  bubble,
  values,
  proactive,
  path,
  onAsk,
  onSilence,
}: AssistantBubbleProps) {
  const t = useTranslations("assistantWidget");
  return (
    <div
      className={cn(
        "bg-background border-border fixed right-4 bottom-36 z-50 max-w-[17rem] rounded-2xl rounded-br-sm border shadow-lg md:right-6 md:bottom-24",
        !proactive && "hidden md:block",
      )}
    >
      <button
        type="button"
        onClick={() => onAsk(t(`bubbles.${bubble}.ask`, values))}
        className="block w-full px-4 py-3 pr-9 text-left text-sm leading-snug"
      >
        {t(`bubbles.${bubble}.say`, values)}
      </button>
      <button
        type="button"
        aria-label={t("silenceHere")}
        onClick={() => {
          silencePage(path);
          onSilence();
        }}
        className="text-muted-foreground hover:text-foreground absolute top-2 right-2 rounded-md p-1"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
