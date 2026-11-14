"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import {
  ChevronRight,
  CircleAlert,
  Check,
  MessageCircleQuestion,
  OctagonPause,
  ShieldCheck,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { ThinkingOrb } from "@/components/ui/thinking-orb";
import { formatElapsed } from "@/lib/elapsed";
import { cn } from "@/lib/utils";

/**
 * How long this turn has been working, ticking while it streams and frozen after.
 *
 * Null for a turn that was never watched live - a reloaded one - which has to take
 * its duration from the run instead. Measured from the turn's own timestamp, so a
 * page opened mid-turn counts from when the turn began rather than from now.
 */
export function useTurnElapsed(startedAt: Date | undefined, running: boolean): number | null {
  const [elapsed, setElapsed] = useState<number | null>(null);
  // The start as a number: a streamed turn's message is rebuilt on every delta,
  // and keyed on the `Date` itself the interval was torn down and set up again
  // with each one.
  const start = startedAt?.getTime();
  useEffect(() => {
    if (!running || start === undefined) return;
    const tick = () => setElapsed(Date.now() - start);
    // The label only shows whole seconds; rebuilding a long activity timeline
    // four times a second adds renders without conveying more progress.
    const id = window.setInterval(tick, 1000);
    return () => {
      window.clearInterval(id);
      // The last reading stands as the turn's duration once it stops.
      tick();
    };
  }, [running, start]);
  return elapsed;
}

/**
 * How long a running turn may go without its process stamping itself alive
 * before the fold says so. A live run beats every 15 seconds, and the
 * conversation listing re-reads every 30 seconds while the live-update
 * socket is up (4 seconds while it is down), so a healthy run's last beat
 * can read up to ~45 seconds old through this channel; 90 seconds is past
 * that noise and still 30 seconds before the stale-run sweep ends the run
 * at 120. A hung model call keeps beating, so this does not catch a hang -
 * the per-request timeout ends that instead. What it catches is a process
 * that has gone quiet.
 */
export const STALLED_AFTER_MS = 90_000;

/** "Working for 5s…" over a turn still at work, with a light passing over it. */
export function WorkingLine({
  elapsedMs,
  expanded,
  onToggle,
}: {
  elapsedMs: number | null;
  expanded?: boolean;
  onToggle?: () => void;
}) {
  const t = useTranslations("chat.steps");
  const Line = onToggle ? "button" : "p";
  return (
    // The orb sits in the same slot as the finished fold's mark, inside the
    // column: a negative margin pulled it past the transcript's edge, which
    // clips it.
    <Line
      type={onToggle ? "button" : undefined}
      role={onToggle ? undefined : "status"}
      aria-expanded={expanded}
      onClick={onToggle}
      className={cn(
        "flex items-center gap-2 py-0.5 text-left text-[13px]",
        onToggle &&
          "text-muted-foreground hover:text-foreground min-h-9 rounded-md focus-visible:outline-2 focus-visible:outline-offset-2",
      )}
    >
      <span className="flex size-5 shrink-0 items-center justify-center">
        <ThinkingOrb state="breathing" size={20} className="h-6 w-6 opacity-80" />
      </span>
      <span className="shimmer-text font-medium">
        {elapsedMs === null
          ? t("working")
          : t("workingFor", { duration: formatElapsed(elapsedMs, t) })}
      </span>
      {onToggle && (
        <ChevronRight
          aria-hidden
          className={cn(
            "size-3.5 shrink-0 transition-transform motion-reduce:transition-none",
            expanded && "rotate-90",
          )}
        />
      )}
    </Line>
  );
}

/**
 * The work before an answer, as one line: "Worked for 12s · 3 steps".
 *
 * A finished turn showed every thought, call and aside above its answer - a turn
 * that read three files and checked a list arrived as five lines of narration
 * before the first word anybody asked for. What a reader wants afterwards is that
 * work happened, how long it took and where to find it; the line says that and
 * opens onto the same steps it replaced.
 */
export function WorkFold({
  steps,
  durationMs,
  stopped = false,
  failed = false,
  running = false,
  waiting,
  children,
  activity,
  live = false,
  lastHeartbeatAt,
}: {
  /** Tool calls folded away; none means the turn only thought. */
  steps: number;
  durationMs: number | null;
  /** The run was stopped, which the line says instead of "Worked". */
  stopped?: boolean;
  failed?: boolean;
  running?: boolean;
  waiting?: "awaiting_answer" | "awaiting_approval";
  children: ReactNode;
  /** A short live action label, never a streaming thought or a nested tool card. */
  activity?: string;
  /** Show progress in place until the run settles; finished history stays scrollable. */
  live?: boolean;
  /** When the run behind this turn last stamped itself alive, if known. */
  lastHeartbeatAt?: Date;
}) {
  const t = useTranslations("chat.steps");
  const tChat = useTranslations("chat");
  const [open, setOpen] = useState(live);
  const historyId = useId();
  const toggleId = useId();
  const duration = durationMs === null ? null : formatElapsed(durationMs, t);
  const runText = useTranslations("pages.runs");
  // Stalled is a sub-state of running, not a terminal one: the run is still
  // going as far as the console knows, but its process has gone quiet. The
  // age is read off the same one-second tick as the turn's own elapsed time,
  // so the label stays current without reading the clock during render.
  // When the turn stops, the last reading stands - but the guard below
  // keeps it from ever calling a finished turn stalled.
  const heartbeatAgeMs = useTurnElapsed(lastHeartbeatAt, running);
  const stalledMs = running ? heartbeatAgeMs : null;
  const stalledFor =
    stalledMs !== null && stalledMs > STALLED_AFTER_MS ? formatElapsed(stalledMs, t) : null;
  const label = failed
    ? duration === null
      ? t("failedWork", { count: steps })
      : t("failedAfter", { duration, count: steps })
    : waiting
      ? runText("toolState", { status: waiting })
      : stalledFor !== null
        ? t("stalledFor", { duration: stalledFor })
        : running
          ? duration === null
            ? t("working")
            : t("workingFor", { duration })
          : stopped
            ? duration === null
              ? t("stopped", { count: steps })
              : t("stoppedAfter", { duration, count: steps })
            : steps === 0
              ? duration === null
                ? tChat("thoughtAboutIt")
                : t("thoughtFor", { duration })
              : duration === null
                ? t("worked", { count: steps })
                : t("workedFor", { duration, count: steps });

  return (
    <div>
      <button
        type="button"
        id={toggleId}
        aria-controls={open ? historyId : undefined}
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
        className="group text-muted-foreground hover:text-foreground hover:bg-muted/60 focus-visible:ring-ring flex min-h-8 w-full min-w-0 items-center gap-2 rounded-lg py-1 text-left text-[13px] transition-colors focus-visible:ring-2 focus-visible:outline-none motion-reduce:transition-none"
      >
        <span className="flex size-5 shrink-0 items-center justify-center" aria-hidden>
          {failed ? (
            <CircleAlert className="text-destructive size-3.5" />
          ) : waiting === "awaiting_approval" ? (
            <ShieldCheck className="size-3.5 text-amber-700 dark:text-amber-400" />
          ) : waiting === "awaiting_answer" ? (
            <MessageCircleQuestion className="size-3.5" />
          ) : stopped ? (
            <OctagonPause className="size-3.5" />
          ) : running ? (
            <ThinkingOrb state="breathing" size={20} className="size-5 opacity-80" />
          ) : (
            <Check className="size-3.5" />
          )}
        </span>
        <span
          className={cn(
            "shrink-0 leading-5 whitespace-nowrap tabular-nums",
            (running || waiting) && "text-foreground/85",
          )}
        >
          {label}
        </span>
        <ChevronRight
          aria-hidden
          className={cn(
            "size-3.5 shrink-0 opacity-50 transition-transform motion-reduce:transition-none",
            open && "rotate-90",
          )}
        />
        {!open && running && activity && (
          <span className="text-muted-foreground min-w-0 flex-1 truncate text-xs" title={activity}>
            {activity}
          </span>
        )}
        {running && steps > 0 && (
          <span
            className={cn(
              "text-muted-foreground shrink-0 text-xs",
              activity && !open && "hidden sm:inline",
            )}
          >
            {t("activityCount", { count: steps })}
          </span>
        )}
      </button>
      {open && (
        <div
          id={historyId}
          role="region"
          aria-labelledby={toggleId}
          // Focus lets keyboard users scroll to steps outside the visible region.
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
          tabIndex={0}
          className={cn(
            "focus-visible:ring-ring mt-2 rounded-lg p-1 focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset",
            !live && "max-h-[min(24rem,50dvh)] scrollbar-thin overflow-y-auto overscroll-contain",
          )}
        >
          <div className="space-y-2">{children}</div>
        </div>
      )}
    </div>
  );
}
