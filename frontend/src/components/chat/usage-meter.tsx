"use client";

import { Gauge } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { AnimatedAmount, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { ConversationWorkspace } from "@/lib/conversation-workspace-api";
import type { ConversationCost, TurnUsage } from "@/types";

interface UsageMeterProps {
  /** The last turn's usage, or `null` before one has been measured. */
  usage: TurnUsage | null;
  /**
   * What the whole thread has cost, from the server rather than from the page.
   *
   * What one *answer* cost is drawn under that answer by `MessageCost`; this is
   * the thread. Summed server-side because the transcript is paged: adding up
   * what is on screen would answer "the first hundred turns" under a label that
   * says otherwise.
   */
  total?: ConversationCost | null;
  /**
   * The workspace as it stands *now*, which is not what a turn cost.
   *
   * Two sources for one reading, on purpose. A live turn reports the workspace it
   * just used, including a container's resident memory - which only its host can
   * answer. A conversation somebody has just *opened* has no turn to report
   * anything, and the listing answers it for a stored workspace at no extra cost,
   * because the panel beside the transcript has already asked.
   */
  workspace?: ConversationWorkspace | null;
  /**
   * How many tokens the model selected *now* accepts, or `null` if nobody knows.
   *
   * The denominator of the context share, and it deliberately does not travel
   * with the reading: how much history there is survives a model change, what
   * share of a window that is does not. Null draws no share at all - a share
   * against an assumed window is a guess presented as a measurement.
   */
  contextWindow?: number | null;
}

/** The share of a budget or a workspace from which it is a warning. */
const ALERT = 80;
/** The context share from which it is a warning; the window fails harder. */
const CONTEXT_ALERT = 75;
/** Where every one of them turns from a warning into an emergency. */
const CRITICAL = 90;

type Level = "calm" | "warning" | "critical";

/** A translator, which the helpers below need because their answers are read. */
type Translate = (key: string, values?: Record<string, string | number>) => string;

/**
 * What this conversation is using, as one icon beside the send button.
 *
 * Four readings - the context share, the money, the budgets, the workspace -
 * used to be a line of their own under the composer, and a line of numbers is a
 * line everybody has to read past on every message to find out that nothing is
 * wrong. They are one control now: a disc that fills with the context window,
 * because that is the ceiling a turn hits without warning, and turns amber or
 * red when *any* of the readings is near its limit. The numbers are one click
 * away, all of them, with the room to say what each one is a share of.
 *
 * Each reading renders itself or nothing, and nothing is drawn as zeroes: "0
 * tokens" under a conversation that has not run anything is a claim. With no
 * reading at all there is no icon either.
 */
export function UsageMeter({
  usage,
  workspace = null,
  total = null,
  contextWindow = null,
}: UsageMeterProps) {
  const t = useTranslations("chat.usage");
  const context = contextOf(usage, contextWindow);
  const fill = usage === null ? null : fillOf(usage, workspace, t);
  const agentShare = usage?.agent_budget_percent ?? null;
  const orgShare = usage?.budget_percent ?? null;
  if (context === null && total === null && fill === null) return null;

  const level = worst([
    levelOf(context?.percent ?? null, CONTEXT_ALERT),
    levelOf(agentShare, ALERT),
    levelOf(orgShare, ALERT),
    levelOf(fill?.percent ?? null, ALERT),
  ]);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={level === "calm" ? t("label") : t("labelNearLimit")}
          title={level === "calm" ? t("label") : t("labelNearLimit")}
          className={cn(
            "hover:bg-foreground/[0.06] inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors",
            TONE[level],
          )}
        >
          {context === null ? (
            <Gauge className="h-4 w-4" aria-hidden />
          ) : (
            <ContextPie percent={context.percent} />
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        className="border-border bg-popover w-[300px] rounded-xl border p-1.5 shadow-md"
      >
        <dl className="text-xs">
          {context !== null && (
            <Reading
              label={t("context")}
              value={t("percent", { percent: share(context.percent) })}
              detail={t("contextOf", { used: context.used, window: context.window })}
              level={levelOf(context.percent, CONTEXT_ALERT)}
            />
          )}
          {total !== null && <SpendReading total={total} />}
          {agentShare !== null && (
            <Reading
              label={t("agentBudget")}
              value={t("monthShare", { percent: agentShare })}
              detail={t("agentBudgetDetail")}
              level={levelOf(agentShare, ALERT)}
            />
          )}
          {orgShare !== null && (
            <Reading
              label={t("orgBudget")}
              value={t("monthShare", { percent: orgShare })}
              detail={t("orgBudgetDetail")}
              level={levelOf(orgShare, ALERT)}
            />
          )}
          {fill !== null && <WorkspaceReading fill={fill} />}
        </dl>
      </PopoverContent>
    </Popover>
  );
}

/** A reading's colour, from the same three levels the icon uses. */
const TONE: Record<Level, string> = {
  calm: "text-muted-foreground hover:text-foreground",
  warning: "text-amber-600",
  critical: "text-destructive",
};

function levelOf(percent: number | null, alert: number): Level {
  if (percent === null) return "calm";
  if (percent >= CRITICAL) return "critical";
  return percent >= alert ? "warning" : "calm";
}

function worst(levels: Level[]): Level {
  if (levels.includes("critical")) return "critical";
  return levels.includes("warning") ? "warning" : "calm";
}

/**
 * How full the model's context window was on the last request, or `null`.
 *
 * It measures **what went out**, which is why it falls when compaction works: the
 * count is taken after the strategies have edited the history. The window comes
 * from the model selected now - a 500,000-token history is 50% of a 1M-context
 * model and 390% of a 128K one, and the second is a request the provider refuses.
 */
function contextOf(
  usage: TurnUsage | null,
  window: number | null,
): { percent: number; used: number; window: number } | null {
  const context = usage?.context ?? null;
  if (context === null || window === null || window <= 0) return null;
  const used = context.used_tokens;
  return { percent: (used * 100) / window, used, window };
}

/**
 * A disc that fills with the context share, clockwise from twelve.
 *
 * A pie rather than a ring: a thin arc a tenth of the way round, beside a send
 * button, is what a loading spinner looks like - and read as one, it said the
 * conversation was busy. Past the window it is simply full.
 */
function ContextPie({ percent }: { percent: number }) {
  const radius = 6.5;
  const filled = Math.min(100, percent) / 100;
  const angle = filled * 2 * Math.PI;
  const x = 8 + radius * Math.sin(angle);
  const y = 8 - radius * Math.cos(angle);
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden>
      <circle cx="8" cy="8" r={radius} fill="currentColor" fillOpacity={0.22} />
      {filled >= 1 ? (
        <circle data-testid="context-fill" cx="8" cy="8" r={radius} fill="currentColor" />
      ) : (
        <path
          data-testid="context-fill"
          fill="currentColor"
          d={`M8 8 L8 ${8 - radius} A${radius} ${radius} 0 ${filled > 0.5 ? 1 : 0} 1 ${x.toFixed(3)} ${y.toFixed(3)} Z`}
        />
      )}
    </svg>
  );
}

/** One row of the popover: what it is, its value, and what the value is a share of. */
function Reading({
  label,
  value,
  detail,
  level = "calm",
  children,
}: {
  label: string;
  value: ReactNode;
  detail: string;
  level?: Level;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-lg px-2.5 py-2">
      <div className="flex items-baseline justify-between gap-3">
        <dt className="text-muted-foreground">{label}</dt>
        <dd
          className={cn(
            "text-foreground font-medium tabular-nums",
            level === "warning" && "text-amber-600",
            level === "critical" && "text-destructive",
          )}
        >
          {value}
        </dd>
      </div>
      {children}
      <p className="text-muted-foreground mt-0.5 leading-snug">{detail}</p>
    </div>
  );
}

/**
 * What the conversation has cost.
 *
 * **Money only - the token count is the detail line.** Two counts of tokens can
 * never agree: a conversation whose context peaked at 3,868 had been billed
 * 7,747, because the input is re-sent and re-paid for on every turn.
 *
 * Prefixed `≥` when any turn in it reached a model with no price entry: one
 * unpriced request makes the whole total a floor.
 *
 * **Cents, until there are none.** Two decimals from a cent upwards; below one,
 * two would print `$0.00` under a conversation that did cost something, so a
 * sub-cent total keeps four.
 */
function SpendReading({ total }: { total: ConversationCost }) {
  const t = useTranslations("chat.usage");
  const partial = total.cost_is_partial === true;
  const cost = Number(total.cost_usd);
  const decimals = cost === 0 || Math.abs(cost) >= 0.01 ? 2 : 4;
  const values = { cost: cost.toFixed(decimals) };
  const detail = { input: total.input_tokens, output: total.output_tokens };

  return (
    <Reading
      label={t("conversation")}
      value={
        <>
          {/* The `≥` stays outside the counter and outside the catalog: it is a
              glyph, and inside `AnimatedAmount` it would roll as though it were
              a digit. The counter is handed the whole sentence as its label. */}
          {partial ? (
            // i18n-exempt: a mathematical sign, not copy - the sentence it opens
            // is `threadTotalPartial`, which is what this counter announces.
            <span aria-hidden>≥ </span>
          ) : null}
          <AnimatedAmount
            value={total.cost_usd}
            decimals={decimals}
            label={partial ? t("threadTotalPartial", values) : t("threadTotal", values)}
          />
        </>
      }
      detail={partial ? t("threadTotalPartialDetail", detail) : t("threadTotalDetail", detail)}
    />
  );
}

/**
 * How full the scratch space is, with a bar because the number alone is easy to miss.
 *
 * A stored workspace that fills up starts *refusing writes*, and the agent reports
 * that as a tool error in the middle of doing something rather than as "you are
 * out of room".
 */
function WorkspaceReading({ fill }: { fill: Fill }) {
  const t = useTranslations("chat.usage");
  const label = fill.kind === "memory" ? t("sandboxMemory") : t("workspace");
  // Under one per cent the amount says more than the share does - see `Fill.used`.
  const shown =
    fill.percent !== null && (fill.percent >= 1 || fill.used === null) ? fill.percent : null;
  const value =
    shown !== null
      ? t("percent", { percent: shown })
      : fill.percent === null
        ? t("inUse")
        : fill.used;
  const level = levelOf(fill.percent, ALERT);

  return (
    <Reading label={label} value={value} detail={fill.detail} level={level}>
      {shown !== null && (
        <span
          className="bg-muted mt-1.5 block h-1 w-full overflow-hidden rounded-full"
          role="progressbar"
          aria-valuenow={shown}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={t("workspaceUsed")}
        >
          <span
            className={cn(
              "block h-full rounded-full",
              level === "critical"
                ? "bg-destructive"
                : level === "warning"
                  ? "bg-amber-500"
                  : "bg-foreground/40",
            )}
            style={{ width: `${Math.min(100, shown)}%` }}
          />
        </span>
      )}
    </Reading>
  );
}

interface Fill {
  percent: number | null;
  /**
   * What is actually in use, formatted, for when the share says nothing.
   *
   * A container with a 2 GiB ceiling holding 760 KiB is 0.036% full, which the
   * server rounds to `0` - a gauge that reads the same on every ordinary turn.
   * Under one per cent the amount is the honest thing to print.
   */
  used: string | null;
  detail: string;
  /**
   * Which ceiling this is a share of: a container's resident **memory** against
   * the ceiling its host set, or a stored workspace's bytes against a cap this
   * platform holds (#1039).
   */
  kind: "memory" | "stored";
}

/** How full the workspace is, from whichever source can say. */
function fillOf(
  usage: TurnUsage,
  workspace: ConversationWorkspace | null,
  t: Translate,
): Fill | null {
  const sandbox = usage.sandbox;
  if (sandbox !== null)
    return {
      percent: sandbox.percent,
      used: usedOf(sandbox),
      detail: reportedDetail(sandbox, t),
      // Bytes first, matching `SandboxUsage.percent` on the server: whichever
      // pair it measured is the pair this describes.
      kind: sandbox.bytes_used !== null && sandbox.bytes_limit !== null ? "stored" : "memory",
    };
  // No turn has reported one - a reopened conversation. A stored workspace can still
  // be measured from the listing; a container cannot, and "in use" would claim a
  // sandbox is running when the last one may have been reaped weeks ago.
  if (workspace === null || workspace.backend !== "state" || workspace.bytes_limit === null)
    return null;
  return {
    percent: Math.round((workspace.bytes_total * 100) / workspace.bytes_limit),
    used: size(workspace.bytes_total),
    detail: t("storedOf", {
      used: size(workspace.bytes_total),
      limit: size(workspace.bytes_limit),
    }),
    kind: "stored",
  };
}

/**
 * The share, at a precision that still moves when the window is barely touched.
 *
 * A whole number is right at 75% and useless at 0.4%: a first turn is a few
 * hundred tokens against hundreds of thousands, and rounding that to `0` reads as
 * "nothing was measured" rather than as "barely touched".
 */
function share(percent: number): string {
  if (percent >= 10) return String(Math.round(percent));
  if (percent >= 1) return percent.toFixed(1);
  return percent.toFixed(2);
}

/** Bytes as a person reads them. */
function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KiB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  // A 2 GiB ceiling printed as `2048.0 MiB` reads like a quota for a whole
  // installation rather than one container's limit.
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GiB`;
}

/** How much is in use, formatted, whichever pair the backend reported. */
function usedOf(sandbox: NonNullable<TurnUsage["sandbox"]>): string | null {
  if (sandbox.bytes_used !== null) return size(sandbox.bytes_used);
  if (sandbox.memory_bytes !== null) return size(sandbox.memory_bytes);
  return null;
}

/** What the workspace reading is measuring, and how much of it is gone. */
function reportedDetail(sandbox: NonNullable<TurnUsage["sandbox"]>, t: Translate): string {
  if (sandbox.bytes_used !== null && sandbox.bytes_limit !== null)
    return t("storedOf", { used: size(sandbox.bytes_used), limit: size(sandbox.bytes_limit) });
  if (sandbox.memory_bytes !== null && sandbox.memory_limit_bytes !== null)
    return t("inContainer", {
      used: size(sandbox.memory_bytes),
      limit: size(sandbox.memory_limit_bytes),
    });
  return t("unmeasured");
}
