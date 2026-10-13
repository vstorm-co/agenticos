"use client";

import { useEffect, useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
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
  useEffect(() => {
    if (!running || startedAt === undefined) return;
    const tick = () => setElapsed(Date.now() - startedAt.getTime());
    const id = window.setInterval(tick, 1000);
    return () => {
      window.clearInterval(id);
      // The last reading stands as the turn's duration once it stops.
      tick();
    };
  }, [running, startedAt]);
  return elapsed;
}

/** "Working for 5s…" over a turn still at work, with a light passing over it. */
export function WorkingLine({ elapsedMs }: { elapsedMs: number | null }) {
  const t = useTranslations("chat.steps");
  return (
    <p role="status" className="flex items-center gap-2 text-[13px]">
      <ThinkingOrb state="breathing" size={20} className="-my-2 -ml-1 h-6 w-6 opacity-80" />
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
  children,
}: {
  /** Tool calls folded away; none means the turn only thought. */
  steps: number;
  durationMs: number | null;
  children: ReactNode;
}) {
  const t = useTranslations("chat.steps");
  const tChat = useTranslations("chat");
  const [open, setOpen] = useState(false);
  const duration = durationMs === null ? null : formatElapsed(durationMs, t);
  const label =
    steps === 0
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
          {!open && (
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
