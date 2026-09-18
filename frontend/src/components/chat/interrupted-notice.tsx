"use client";

import { Unplug } from "lucide-react";
import { useTranslations } from "next-intl";

interface InterruptedNoticeProps {
  /** True while a turn whose socket went away is unresolved. */
  interrupted: boolean;
  /** Read the transcript again. The turn lands there, not on the socket. */
  onRecheck?: () => void;
}

/**
 * Says the connection went away while the agent was answering.
 *
 * Every frame that ends a turn arrives on the socket, so a socket that dropped
 * mid-answer ends nothing on screen: the composer spun until somebody reloaded
 * the page, and there was no reading of that screen except "it has broken".
 *
 * The answer itself is not lost - `AgentSession.shutdown` lets the turn reach its
 * end and write itself to the transcript - so this says the one true thing about
 * that state and offers the one action that resolves it. It sits above the
 * composer, beside `CompactionNotice`, for the same reason that one does:
 * nothing here is persisted, and a reopened conversation must not find a step
 * describing plumbing.
 *
 * The re-read is a button rather than a poll because the turn finishes when it
 * finishes. A reader who has waited long enough presses it; one who would rather
 * ask something else types instead, which also clears this.
 */
export function InterruptedNotice({ interrupted, onRecheck }: InterruptedNoticeProps) {
  const t = useTranslations("chat");
  if (!interrupted) return null;

  return (
    <div
      className="mb-2 flex items-center gap-2 px-1 text-xs text-amber-600"
      role="status"
      aria-live="polite"
    >
      <Unplug className="h-3 w-3" aria-hidden />
      <span>{t("turnInterrupted")}</span>
      {onRecheck && (
        <button type="button" onClick={onRecheck} className="underline underline-offset-2">
          {t("turnInterruptedRecheck")}
        </button>
      )}
    </div>
  );
}
