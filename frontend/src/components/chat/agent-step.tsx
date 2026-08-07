"use client";

import { Children, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  BarChart3,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  Code2,
  FilePenLine,
  FilePlus2,
  FileText,
  FolderOpen,
  Globe,
  PauseCircle,
  Plug,
  Search,
  TerminalSquare,
  Users,
  Wrench,
  X,
} from "lucide-react";

import { logoDataUri } from "@/lib/mcp-catalog";
import { cn } from "@/lib/utils";
import type { StepKind } from "@/lib/tool-catalog";

const ICONS: Record<StepKind, typeof FileText> = {
  write: FilePlus2,
  edit: FilePenLine,
  read: FileText,
  list: FolderOpen,
  search: Search,
  shell: TerminalSquare,
  chart: BarChart3,
  knowledge: BookOpen,
  web: Globe,
  skill: BookOpen,
  code: Code2,
  delegate: Users,
  mcp: Plug,
  tool: Wrench,
};

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
 * One element around the run rather than a border on each row, because the line has to
 * be *continuous*: gaps between individually bordered rows read as a dashed line, which
 * says something this does not mean.
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
    <div className="border-foreground/10 space-y-0.5 border-l pl-3.5">
      {folded ? (
        <button
          type="button"
          onClick={() => setOpened(true)}
          aria-expanded={false}
          className="text-muted-foreground/70 hover:text-foreground flex items-center gap-2 py-1 text-[13px]"
        >
          <ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden />
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
  /** The subject, when the label did not already carry it. */
  detail?: string | null;
  kind: StepKind;
  state: "running" | "done" | "error" | "parked";
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
  detail,
  kind,
  state,
  expanded,
  onToggle,
  actions,
  children,
}: AgentStepProps) {
  const t = useTranslations("chat.steps");
  const Icon = state === "parked" ? PauseCircle : ICONS[kind];
  const openable = onToggle !== undefined;
  // The server's brand, where there is one, and the generic plug where there is not.
  // A step that says "Linear · Create issue" beside Linear's mark is legible at a
  // glance in a way a row of identical wrenches never was.
  const brand =
    logoDomain !== null && logoDomain !== undefined && state !== "parked"
      ? logoDataUri(logoDomain)
      : null;

  const line = (
    <>
      {brand !== null ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={brand}
          alt=""
          className={cn("h-3.5 w-3.5 shrink-0 rounded-sm", state === "running" && "animate-pulse")}
        />
      ) : (
        <Icon
          className={cn(
            "h-3.5 w-3.5 shrink-0",
            state === "running" && "text-brand animate-pulse",
            state === "error" && "text-destructive",
            state === "parked" && "text-amber-600",
            state === "done" && "text-muted-foreground/70",
          )}
          aria-hidden
        />
      )}
      <span
        className={cn(
          "min-w-0 truncate text-[13px]",
          state === "error" ? "text-destructive" : "text-muted-foreground",
          state === "running" && "text-foreground/70",
        )}
      >
        {label}
      </span>
      {detail !== null && detail !== undefined && (
        <span className="text-muted-foreground/60 min-w-0 flex-1 truncate font-mono text-[11px]">
          {detail}
        </span>
      )}
      {state === "parked" && (
        <span className="shrink-0 text-[11px] text-amber-600">{t("awaitingApproval")}</span>
      )}
      {state === "error" && (
        <X className="text-destructive h-3 w-3 shrink-0" aria-label={t("failed")} />
      )}
      {state === "running" && (
        <span className="flex shrink-0 gap-0.5" aria-label={t("running")}>
          <span className="bg-brand/60 h-1 w-1 animate-bounce rounded-full [animation-delay:0ms]" />
          <span className="bg-brand/60 h-1 w-1 animate-bounce rounded-full [animation-delay:150ms]" />
          <span className="bg-brand/60 h-1 w-1 animate-bounce rounded-full [animation-delay:300ms]" />
        </span>
      )}
    </>
  );

  return (
    <div className="group/step step-in relative py-1">
      {/* The icon sits on the rail rather than beside it, which is what makes a run
          of steps read as one thread instead of an indented list. */}
      <div className="flex items-center gap-2">
        {openable ? (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            className="hover:text-foreground flex max-w-full min-w-0 items-center gap-2 rounded-md text-left"
          >
            {line}
            <ChevronDown
              className={cn(
                "text-muted-foreground/50 h-3 w-3 shrink-0 transition-transform",
                "opacity-0 group-hover/step:opacity-100",
                expanded && "rotate-180 opacity-100",
              )}
              aria-hidden
            />
          </button>
        ) : (
          <span className="flex min-w-0 items-center gap-2">{line}</span>
        )}
        {expanded && actions}
      </div>

      {expanded && children !== undefined && <div className="pt-2 pb-1">{children}</div>}
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
    <div className="flex items-center gap-2 py-1">
      <Check className="text-muted-foreground/70 h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="text-muted-foreground text-[13px]">{t("done")}</span>
    </div>
  );
}
