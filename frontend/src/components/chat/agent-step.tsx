"use client";

import { Children, useId, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Check, ChevronDown, ChevronRight, LoaderCircle, X, type LucideIcon } from "lucide-react";

import { logoDataUri } from "@/lib/mcp-catalog";
import { cn } from "@/lib/utils";
import styles from "./agent-step.module.css";
import { STEP_ICONS } from "@/lib/step-icons";
import type { StepKind } from "@/lib/tool-catalog";

interface AgentStepsProps {
  children: ReactNode;
  /**
   * Show every step rather than only the last.
   *
   * For a run holding something a person has to see: a call that failed, or one parked
   * waiting for their approval. Folding those away would hide the one line in the turn
   * that was asking for something.
   */
  showAll?: boolean;
  /** Close the run with "Done" - only worth it after several steps. */
  done?: boolean;
}

/**
 * The rail a run of steps hangs from, showing the one that matters.
 *
 * Connect icon centres through the gutter, ending at the final step's icon.
 * Expanded details stay to the right of that gutter so the rail never crosses content.
 *
 * **Only the last step stays open.** A turn that reads three files, greps twice and
 * writes one pushes the answer off the screen with work nobody asked to watch - and the
 * step that is worth reading is the current one while it runs and the last one
 * afterwards. The earlier ones become a line saying how many there were, which is the
 * honest summary: it says work happened and where to find it, rather than hiding it.
 *
 * Two earlier steps is the threshold. Folding a single line behind a control that costs
 * a line saves nothing.
 */
export function AgentSteps({ children, showAll = false, done = false }: AgentStepsProps) {
  const t = useTranslations("chat.steps");
  const [opened, setOpened] = useState(false);
  const steps = Children.toArray(children);
  const earlier = steps.slice(0, -1);
  const current = steps.at(-1);
  const folded = !showAll && !opened && earlier.length >= 2;

  return (
    <div className={`${styles.steps} relative space-y-0.5`}>
      {folded ? (
        <button
          type="button"
          onClick={() => setOpened(true)}
          aria-expanded={false}
          className="text-muted-foreground hover:text-foreground relative flex min-h-8 items-center gap-2 rounded-md px-1.5 py-1 text-[13px]"
        >
          <span className="bg-background relative flex size-5 shrink-0 items-center justify-center">
            <ChevronRight className="size-3.5" aria-hidden />
          </span>
          {t("earlierSteps", { count: earlier.length })}
        </button>
      ) : (
        earlier
      )}
      {current}
      {done && <StepsDone />}
    </div>
  );
}

interface AgentStepProps {
  label: string;
  /** An MCP server's domain, whose logo stands in for the icon. */
  logoDomain?: string | null;
  /**
   * What stands in for the icon once the step has landed - a delegate's face, so
   * "Asked Finance Analyst" is drawn with the agent that was asked.
   */
  mark?: ReactNode;
  /** The subject, when the label did not already carry it. */
  detail?: string | null;
  kind: StepKind;
  icon?: LucideIcon;
  state: "running" | "done" | "error" | "parked";
  /**
   * What a parked step waits for. A question's own label already says it waits
   * for an answer, so only an approval carries the amber note.
   */
  parkedOn?: "approval" | "answer";
  expanded: boolean;
  /** Absent when this step has nothing to open, which makes the row plain text. */
  onToggle?: () => void;
  /** Shown beside the chevron once expanded - the raw view toggle, mainly. */
  actions?: ReactNode;
  children?: ReactNode;
}

/**
 * One step of a turn: an icon, a line, and whatever it opens.
 *
 * **A row, not a card.** The card this replaces had a border, a fill, a status pill,
 * a chevron and a raw-view button on every call - so a turn that wrote one file
 * arrived as three boxes of chrome around three short sentences, and the answer
 * itself was below the fold. What somebody scrolling a transcript wants is the
 * narration: *Wrote test1.md*, quiet, one line, in a column they can ignore.
 *
 * Nothing marks a step that simply worked. A tick on every row is a tick that says
 * nothing; what earns a marker is the exception - a failure, or a call parked waiting
 * for somebody to approve it, which produces no result *at all* until they do and
 * must never look like something in flight.
 */
export function AgentStep({
  label,
  logoDomain,
  mark,
  detail,
  kind,
  icon,
  state,
  parkedOn = "approval",
  expanded,
  onToggle,
  actions,
  children,
}: AgentStepProps) {
  const t = useTranslations("chat.steps");
  const Icon = icon ?? STEP_ICONS[kind];
  const detailsId = useId();
  const openable = onToggle !== undefined;
  // The server's brand, where there is one, and the generic plug where there is not.
  // A step that says "Linear · Create issue" beside Linear's mark is legible at a
  // glance in a way a row of identical wrenches never was.
  const brand = logoDomain !== null && logoDomain !== undefined ? logoDataUri(logoDomain) : null;

  const line = (
    <>
      <span
        className="bg-background relative z-10 flex size-5 shrink-0 items-center justify-center"
        aria-hidden
      >
        {state === "running" ? (
          <LoaderCircle className="text-foreground size-3.5 motion-safe:animate-spin" />
        ) : mark !== undefined ? (
          mark
        ) : brand !== null ? (
          // eslint-disable-next-line @next/next/no-img-element -- a bundled brand URI
          <img src={brand} alt="" className="size-3.5 rounded-sm" />
        ) : (
          <Icon
            className={cn(
              "size-3.5",
              state === "error"
                ? "text-destructive"
                : state === "parked"
                  ? "text-amber-700 dark:text-amber-400"
                  : "text-muted-foreground",
            )}
          />
        )}
      </span>
      <span
        className={cn(
          "min-w-0 truncate text-[13px] leading-5",
          state === "error" ? "text-destructive" : "text-foreground/75",
          state === "running" && "text-foreground",
        )}
      >
        {label}
      </span>
      {detail !== null && detail !== undefined && (
        <span className="text-muted-foreground min-w-0 flex-1 truncate font-mono text-xs">
          {detail}
        </span>
      )}
      {state === "parked" && parkedOn === "approval" && (
        <span className="ml-auto shrink-0 rounded-md border border-amber-500/20 bg-amber-500/5 px-1.5 py-0.5 text-[11px] leading-4 text-amber-700 dark:text-amber-400">
          {t("awaitingApproval")}
        </span>
      )}
      {state === "error" && (
        <X className="text-destructive h-3 w-3 shrink-0" aria-label={t("failed")} />
      )}
      {/* Motion is decorative; screen readers get the actual running state. */}
      {state === "running" && <span className="sr-only">{t("running")}</span>}
    </>
  );

  return (
    <div className="group/step relative py-0.5">
      {/* The icon sits on the rail rather than beside it, which is what makes a run
          of steps read as one thread instead of an indented list. */}
      <div className="flex items-center gap-2">
        {openable ? (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            aria-controls={expanded ? detailsId : undefined}
            className="hover:bg-muted/50 focus-visible:ring-ring flex min-h-8 max-w-full min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none motion-reduce:transition-none"
          >
            {line}
            <ChevronDown
              className={cn(
                "text-muted-foreground h-3 w-3 shrink-0 transition-transform",
                "ml-auto opacity-50 group-hover/step:opacity-100",
                expanded && "rotate-180 opacity-100",
              )}
              aria-hidden
            />
          </button>
        ) : (
          <span className="flex min-h-8 min-w-0 items-center gap-2 px-1.5">{line}</span>
        )}
        {expanded && actions}
      </div>

      {expanded && children !== undefined && (
        <div
          id={detailsId}
          className="border-border/60 bg-muted/15 mt-1 mb-2 ml-9 min-w-0 overflow-hidden rounded-lg border p-3"
        >
          {children}
        </div>
      )}
    </div>
  );
}

/**
 * The end of a run of steps.
 *
 * Only after a run of several, and that bound is the point: on a turn that read one
 * file, "Done" is a second line saying what the first already said. On a turn that
 * listed, read, edited and ran a command, it is the line that says the agent stopped
 * working and started answering - which a run ending on "Ran pytest" does not.
 */
function StepsDone() {
  const t = useTranslations("chat.steps");
  return (
    <div className="relative flex min-h-8 items-center gap-2 px-1.5 py-1">
      <span className="bg-background relative flex size-5 shrink-0 items-center justify-center">
        <Check className="text-muted-foreground size-3.5" aria-hidden />
      </span>
      <span className="text-muted-foreground text-[13px]">{t("done")}</span>
    </div>
  );
}
