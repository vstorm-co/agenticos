"use client";

import { Unplug } from "lucide-react";
import { useTranslations } from "next-intl";

interface InterruptedNoticeProps {
  /** True while a turn whose socket went away is unresolved. */
  interrupted: boolean;
  /**
   * True once the reader has asked something else instead of waiting.
   *
   * The earlier answer is still being written and will land in the transcript
   * after the later question - which is confusing exactly once, and only when
   * nothing said it would.
   */
  detached?: boolean;
  /**
   * True when the reader left this conversation while its agent was answering,
   * and has come back before the answer landed.
   */
  left?: boolean;
  /**
   * True when the turn ended and wrote no answer: the process running it died,
   * and the stale-run sweep closed it. Nothing is coming, so the notice stops
   * saying something is and offers to ask again.
   */
  lost?: boolean;
  /** Read the transcript again. The turn lands there, not on the socket. */
  onRecheck?: () => void;
  /** Ask the unanswered question again. */
  onAskAgain?: () => void;
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
export function InterruptedNotice({
  interrupted,
  detached = false,
  left = false,
  lost = false,
  onRecheck,
  onAskAgain,
}: InterruptedNoticeProps) {
  const t = useTranslations("chat");
  if (lost) {
    return (
      <div className="mb-2 flex items-center gap-2 px-1 text-xs text-amber-600" role="status">
        <Unplug className="h-3 w-3" aria-hidden />
        <span>{t("turnLost")}</span>
        {onAskAgain && (
          <button type="button" onClick={onAskAgain} className="underline underline-offset-2">
            {t("turnLostAskAgain")}
          </button>
        )}
      </div>
    );
  }
  if (!interrupted && !detached && !left) return null;

  return (
    <div
      className="mb-2 flex items-center gap-2 px-1 text-xs text-amber-600"
      role="status"
      aria-live="polite"
    >
      <Unplug className="h-3 w-3" aria-hidden />
      <span>
        {interrupted
          ? t("turnInterrupted")
          : detached
            ? t("turnStillArriving")
            : t("turnLeftRunning")}
      </span>
      {onRecheck && (
        <button type="button" onClick={onRecheck} className="underline underline-offset-2">
          {t("turnInterruptedRecheck")}
        </button>
      )}
    </div>
  );
}
