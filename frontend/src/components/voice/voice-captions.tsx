"use client";

import { useTranslations } from "next-intl";

import { captionKey, type Caption } from "@/lib/voice/captions";
import { cn } from "@/lib/utils";

/** How many lines the view shows; the conversation keeps every turn as a message. */
const SHOWN = 6;

/**
 * Word-by-word captions for both sides (#54). The visible words change many
 * times a second, so they are hidden from screen readers; a polite live region
 * announces each line once it is final, with who said it.
 */
export function VoiceCaptions({
  captions,
  agentName,
}: {
  captions: readonly Caption[];
  agentName: string;
}) {
  const t = useTranslations("chat.voice.captions");
  const lastFinal = captions.findLast((line) => line.final);
  return (
    <div>
      <div data-testid="voice-captions-visible" aria-hidden="true" className="space-y-1.5 text-sm">
        {captions.slice(-SHOWN).map((line) => (
          <p
            key={captionKey(line)}
            className={cn(
              line.role === "user" ? "text-foreground" : "text-muted-foreground",
              !line.final && "opacity-80",
            )}
          >
            {line.text}
          </p>
        ))}
      </div>
      <p role="status" aria-live="polite" className="sr-only">
        {lastFinal
          ? lastFinal.role === "user"
            ? t("you", { text: lastFinal.text })
            : t("agent", { agent: agentName, text: lastFinal.text })
          : null}
      </p>
    </div>
  );
}
