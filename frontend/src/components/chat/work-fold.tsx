"use client";

import { useEffect, useState, type ReactNode } from "react";
import { ChevronRight, OctagonPause } from "lucide-react";
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
    // A quarter-second beat, so a second boundary shows within one: on a 1s
    // beat out of phase with the clock, a display lags by almost a second.
    const id = window.setInterval(tick, 250);
    return () => {
      window.clearInterval(id);
      // The last reading stands as the turn's duration once it stops.
      tick();
    };
  }, [running, start]);
  return elapsed;
}

/** "Working for 5s…" over a turn still at work, with a light passing over it. */
export function WorkingLine({ elapsedMs }: { elapsedMs: number | null }) {
  const t = useTranslations("chat.steps");
  return (
    // The orb sits in the same slot as the finished fold's mark, inside the
    // column: a negative margin pulled it past the transcript's edge, which
    // clips it.
    <p role="status" className="flex items-center gap-2 py-0.5 text-[13px]">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center">
        <ThinkingOrb state="breathing" size={20} className="h-6 w-6 opacity-80" />
      </span>
      <span className="shimmer-text font-medium">
        {elapsedMs === null
          ? t("working")
          : t("workingFor", { duration: formatElapsed(elapsedMs, t) })}
      </span>
    </p>
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
  children,
}: {
  /** Tool calls folded away; none means the turn only thought. */
  steps: number;
  durationMs: number | null;
  /** The run was stopped, which the line says instead of "Worked". */
  stopped?: boolean;
  children: ReactNode;
}) {
  const t = useTranslations("chat.steps");
  const tChat = useTranslations("chat");
  const [open, setOpen] = useState(false);
  const duration = durationMs === null ? null : formatElapsed(durationMs, t);
  const label = stopped
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
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
        className="group text-muted-foreground hover:text-foreground flex items-center gap-2 py-0.5 text-[13px] transition-colors"
      >
        <span className="relative flex h-6 w-6 shrink-0 items-center justify-center">
          {/* The mark of work done; the way in once the pointer is on it, and the way
              back - staying put - once it is open. */}
          {!open && stopped && (
            <OctagonPause
              className="h-3.5 w-3.5 transition-opacity group-hover:opacity-0"
              aria-hidden
            />
          )}
          {!open && !stopped && (
            <ThinkingOrb
              state="breathing"
              size={20}
              paused
              className="h-6 w-6 opacity-80 transition-opacity group-hover:opacity-0"
            />
          )}
          <ChevronRight
            className={cn(
              "absolute h-3.5 w-3.5 transition-[transform,opacity]",
              open ? "rotate-90 opacity-100" : "opacity-0 group-hover:opacity-100",
            )}
            aria-hidden
          />
        </span>
        {label}
      </button>
      {open && <div className="mt-2 space-y-3 pl-1">{children}</div>}
    </div>
  );
}
