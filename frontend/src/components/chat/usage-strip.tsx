"use client";

import { Coins, Gauge, HardDrive, MemoryStick } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { ConversationWorkspace } from "@/lib/conversation-workspace-api";
import type { ConversationCost, TurnUsage } from "@/types";

interface UsageStripProps {
  /** The last turn's usage, or `null` before one has been measured. */
  usage: TurnUsage | null;
  /**
   * What the whole thread has cost, from the server rather than from the page.
   *
   * The only money in this strip. What one *answer* cost is drawn under that
   * answer by `MessageCost`, where it can be compared with the answer beside it;
   * repeating it here put the same figure on screen twice with nothing saying
   * which was which - and on a one-turn conversation the two are identical, which
   * is exactly where somebody first meets the strip.
   *
   * Summed server-side because the transcript is paged: adding up what is on
   * screen would answer "the first hundred turns" under a label that says
   * otherwise.
   */
  total?: ConversationCost | null;
  /**
   * The workspace as it stands *now*, which is not what a turn cost.
   *
   * Two sources for one line, on purpose. A live turn reports the workspace it just
   * used, including a container's resident memory - which only its host can answer. A
   * conversation somebody has just *opened* has no turn to report anything, and the
   * fill was therefore missing until they sent a message: the one moment it is least
   * useful. The listing answers it for a stored workspace at no extra cost, because
   * the panel beside the transcript has already asked.
   */
  workspace?: ConversationWorkspace | null;
  /**
   * How many tokens the model selected *now* accepts, or `null` if nobody knows.
   *
   * The denominator of the context gauge, and it deliberately does not travel
   * with the reading: how much history there is survives a model change, what
   * share of a window that is does not. Null draws no gauge at all - a share
   * against an assumed window is a guess presented as a measurement, and the
   * guess is wrong in the direction that lets a run reach the ceiling.
   */
  contextWindow?: number | null;
}

/** A translator, which the helpers below need because their answers are read. */
type Translate = (key: string, values?: Record<string, string | number>) => string;

/**
 * Three readings under the composer, and they are three different quantities.
 *
 * **Context** is how much of the model's window the last request occupied — what
 * was *sent*, after any compaction, not what the conversation holds. **Spend** is
 * what the whole thread has cost. **Workspace** is disk. They were confusable
 * mostly because a fourth reading — what the last turn cost — sat unlabelled
 * beside the thread total and was identical to it on a one-turn chat.
 *
 * Each segment renders itself or nothing, and nothing is drawn as zeroes: "0
 * tokens" under a conversation that has not run anything is a claim, and this has
 * none to make yet.
 *
 * **The row it occupies is not absent, though.** The strip sits inside the composer,
 * so appearing after the first answer grew the box somebody had just typed in and
 * shifted the whole conversation up a line. The line is reserved whether or not there
 * is anything to put in it: one line of `text-xs` is 1rem, which is exactly what the
 * populated row measures, so the composer is the same height before and after.
 */
export function UsageStrip({
  usage,
  workspace = null,
  total = null,
  contextWindow = null,
}: UsageStripProps) {
  return (
    <div className="text-muted-foreground flex min-h-4 flex-wrap items-center gap-x-4 gap-y-1 px-1 text-xs">
      <ContextSegment context={usage?.context ?? null} window={contextWindow} />
      <SpendSegment total={total} usage={usage} />
      <WorkspaceSegment usage={usage} workspace={workspace} />
    </div>
  );
}

/**
 * How full the model's context window was on the last request.
 *
 * The ceiling nobody sees coming. A budget refuses with a message somebody can
 * act on and a workspace refuses a write; a context window is refused by the
 * *provider*, mid-answer, and the run simply fails. Seeing it climb is the
 * difference — and it is what an agent with no compaction bound has instead of a
 * safety net.
 *
 * It measures **what went out**, which is why it falls when compaction works: the
 * count is taken after the strategies have edited the history, on the messages
 * the request actually carries, not on what the conversation holds in the
 * database.
 *
 * **The window comes from the model selected now, not from the one that produced
 * the reading.** How much history there is survives a model change; what share of
 * a window that is does not. Carried over, a 500,000-token history measured on a
 * 1M-context model would go on reading "50%" after a switch to a 128K one, where
 * it is really 390% and the next request is refused outright. So a switch moves
 * this figure immediately, which is the whole reason to look at it — and where no
 * window can be resolved, nothing is drawn rather than a share against a guess.
 */
function ContextSegment({
  context,
  window,
}: {
  context: TurnUsage["context"];
  window: number | null;
}) {
  const t = useTranslations("chat.usage");
  if (context === null || window === null || window <= 0) return null;
  const used = context.used_tokens;
  const percent = (used * 100) / window;

  return (
    <span className="flex items-center gap-1.5" title={t("contextOf", { used, window })}>
      <Gauge className="h-3 w-3" aria-hidden />
      <span
        className={cn(
          percent >= 90 && "text-destructive",
          percent >= 75 && percent < 90 && "text-amber-600",
        )}
      >
        {t("contextPercent", { percent: share(percent) })}
      </span>
    </span>
  );
}

/**
 * What the conversation has cost, and how much of a monthly cap that leaves.
 *
 * **Money only — the token count lives in the tooltip.** It used to be on the
 * line, beside the context reading, and the two are both counts of tokens that
 * can never agree: a conversation whose context peaked at 3,868 had been billed
 * 7,747, because the input is re-sent and re-paid for on every turn. Read side by
 * side, one of them looks broken. So the strip now carries one figure per unit —
 * a percentage of a window, an amount of money, a percentage of a disk — and
 * nothing invites the comparison.
 *
 * Prefixed `≥` when any turn in it reached a model with no price entry: one
 * unpriced request makes the whole total a floor, and a figure that quietly omits
 * part of the bill is worse than one that admits to it.
 *
 * The budget shares ride here rather than in a segment of their own because they
 * are the same subject — money against a ceiling — and they come off the last
 * turn's report, which is the only thing that knows where the month stands. A
 * reopened conversation has no live turn and so shows the total alone.
 */
function SpendSegment({
  total,
  usage,
}: {
  total: ConversationCost | null;
  usage: TurnUsage | null;
}) {
  const t = useTranslations("chat.usage");
  if (total === null) return null;
  const partial = total.cost_is_partial === true;
  const values = { cost: Number(total.cost_usd).toFixed(4) };
  const detail = { input: total.input_tokens, output: total.output_tokens };

  return (
    <span
      className="flex items-center gap-1.5"
      title={partial ? t("threadTotalPartialDetail", detail) : t("threadTotalDetail", detail)}
    >
      <Coins className="h-3 w-3" aria-hidden />
      {partial ? t("threadTotalPartial", values) : t("threadTotal", values)}
      {/* The agent's own cap first: it is the one whoever is looking at this
          agent can raise. The organization's stops every agent at once and is
          somebody else's to change, so it is only worth the space once it is
          close. */}
      {usage?.agent_budget_percent != null && (
        <span className={cn(usage.agent_budget_percent >= 80 && "text-amber-600")}>
          {t("agentShare", { percent: usage.agent_budget_percent })}
        </span>
      )}
      {usage?.budget_percent != null && usage.budget_percent >= 80 && (
        <span className="text-amber-600">{t("orgShare", { percent: usage.budget_percent })}</span>
      )}
    </span>
  );
}

/**
 * How full the scratch space is, with a bar because the number alone is easy to miss.
 *
 * The warning this strip is really for: a stored workspace that fills up starts
 * *refusing writes*, and the agent reports that as a tool error in the middle of
 * doing something rather than as "you are out of room".
 */
function WorkspaceSegment({
  usage,
  workspace,
}: {
  usage: TurnUsage | null;
  workspace: ConversationWorkspace | null;
}) {
  const t = useTranslations("chat.usage");
  const fill = usage === null ? null : fillOf(usage, workspace, t);
  if (fill === null) return null;

  return (
    <span className="flex items-center gap-1.5" title={fill.detail}>
      {/* The icon carries the same distinction as the words: a chip for memory,
          a disk for bytes kept. */}
      {fill.kind === "memory" ? (
        <MemoryStick className="h-3 w-3" aria-hidden />
      ) : (
        <HardDrive className="h-3 w-3" aria-hidden />
      )}
      {fill.percent === null ? (
        <span>{t("workspaceInUse")}</span>
      ) : (
        <>
          <span
            className={cn(
              fill.percent >= 90 && "text-destructive",
              fill.percent >= 80 && fill.percent < 90 && "text-amber-600",
            )}
          >
            {fill.kind === "memory"
              ? t("sandboxMemoryFull", { percent: fill.percent })
              : t("workspaceFull", { percent: fill.percent })}
          </span>
          {/* A bar as well as the number: 84% and 8% read the same at a glance in
              a line of small grey text, and the whole point of showing this is to
              be noticed before a write is refused. */}
          <span
            className="bg-muted h-1 w-16 overflow-hidden rounded-full"
            role="progressbar"
            aria-valuenow={fill.percent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={t("workspaceUsed")}
          >
            <span
              className={cn(
                // Not a message. A class list went into the catalog during the
                // i18n sweep, where a translator could break the bar.
                "block h-full rounded-full",
                fill.percent >= 90
                  ? "bg-destructive"
                  : fill.percent >= 80
                    ? "bg-amber-500"
                    : "bg-foreground/40",
              )}
              style={{ width: `${Math.min(100, fill.percent)}%` }}
            />
          </span>
        </>
      )}
    </span>
  );
}

interface Fill {
  percent: number | null;
  detail: string;
  /**
   * Which ceiling this is a share of, because they are not the same thing.
   *
   * A container's number is resident **memory** against the ceiling its host
   * set; a stored workspace's is bytes against a cap this platform holds. Both
   * used to read `workspace {percent}% full`, so a sandbox using a tenth of its
   * gigabyte of RAM reported a workspace that was almost empty of *disk* - a
   * sentence about a limit that does not apply, next to a number that is right
   * (#1039).
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
 * "nothing was measured" rather than as "barely touched". Digits are added as the
 * number gets small, which is where they carry information, and dropped as it
 * gets large, where a tenth of a percent is noise beside a ceiling.
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
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

/** What the workspace half is measuring, and how much of it is gone. */
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
