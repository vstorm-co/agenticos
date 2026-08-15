"use client";

import { Coins, Gauge, HardDrive, Receipt } from "lucide-react";
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
   * The last turn answers "what did that answer cost"; this answers "what has
   * this conversation cost me", which is the question somebody actually asks
   * before they stop using it. Summed server-side because the transcript is
   * paged: adding up what is on screen would answer "the first hundred turns"
   * under a label that says otherwise.
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
}

interface Fill {
  percent: number | null;
  detail: string;
}

/** A translator, which the helpers below need because their answers are read. */
type Translate = (key: string, values?: Record<string, string | number>) => string;

/** How full the workspace is, from whichever source can say. */
function fillOf(
  usage: TurnUsage,
  workspace: ConversationWorkspace | null,
  t: Translate,
): Fill | null {
  const sandbox = usage.sandbox;
  if (sandbox !== null) return { percent: sandbox.percent, detail: reportedDetail(sandbox, t) };
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
  };
}

/**
 * How full the model's context window is, drawn beside how full the disk is.
 *
 * The ceiling nobody sees coming. A budget refuses with a message somebody can
 * act on and a workspace refuses a write; a context window is refused by the
 * *provider*, mid-answer, and the run simply fails. Seeing it climb is the
 * difference — and it is what an agent with no compaction bound has instead of a
 * safety net.
 *
 * Marked as an estimate when the window is not the model's real one. A confident
 * "73%" measured against a number nobody could resolve is worse than an
 * uncertain one, because it is acted on.
 */
function ContextFill({
  percent,
  resolved,
  used,
  window,
}: {
  percent: number;
  resolved: boolean;
  used: number;
  window: number;
}) {
  const t = useTranslations("chat.usage");
  const detail = { used, window };

  return (
    <span
      className="flex items-center gap-1.5"
      title={resolved ? t("contextOf", detail) : t("contextOfEstimated", detail)}
    >
      <Gauge className="h-3 w-3" aria-hidden />
      <span
        className={cn(
          percent >= 90 && "text-destructive",
          percent >= 75 && percent < 90 && "text-amber-600",
        )}
      >
        {resolved ? t("contextFull", { percent }) : t("contextFullEstimated", { percent })}
      </span>
    </span>
  );
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

/**
 * What the last turn cost, under the conversation it cost it in.
 *
 * Two numbers, and the second is the one this is really for. Tokens and cost are
 * a sanity check somebody glances at; the workspace bar is a warning — a stored
 * workspace that fills up starts *refusing writes*, and the agent reports that as
 * a tool error in the middle of doing something rather than as "you are out of
 * room". Seeing it approach is the difference.
 *
 * Absent until a turn has been measured, rather than drawn as zeroes: "0 tokens"
 * under a conversation that has not run anything is a claim, and this has none to
 * make yet.
 *
 * **The row it occupies is not absent, though.** The strip sits inside the composer,
 * so appearing after the first answer grew the box somebody had just typed in and
 * shifted the whole conversation up a line. The line is reserved whether or not there
 * is anything to put in it: one line of `text-xs` is 1rem, which is exactly what the
 * populated row measures, so the composer is the same height before and after.
 */
export function UsageStrip({ usage, workspace = null, total = null }: UsageStripProps) {
  return (
    <div className="text-muted-foreground flex min-h-4 flex-wrap items-center gap-x-4 gap-y-1 px-1 text-xs">
      {usage !== null && <Measured usage={usage} workspace={workspace} />}
      {total !== null && <ThreadTotal total={total} />}
    </div>
  );
}

/**
 * What the conversation has cost so far, beside what the last turn cost.
 *
 * Prefixed `≥` when any turn in it reached a model with no price entry: one
 * unpriced request makes the whole total a floor, and a figure that quietly
 * omits part of the bill is worse than one that admits to it.
 */
function ThreadTotal({ total }: { total: ConversationCost }) {
  const t = useTranslations("chat.usage");
  const partial = total.cost_is_partial === true;
  const values = {
    count: total.input_tokens + total.output_tokens,
    cost: Number(total.cost_usd).toFixed(4),
  };
  const detail = { input: total.input_tokens, output: total.output_tokens };

  return (
    <span
      className="flex items-center gap-1.5"
      title={partial ? t("threadTotalPartialDetail", detail) : t("threadTotalDetail", detail)}
    >
      <Receipt className="h-3 w-3" aria-hidden />
      {partial ? t("threadTotalPartial", values) : t("threadTotal", values)}
    </span>
  );
}

/** The numbers themselves, once there are some. */
function Measured({
  usage,
  workspace,
}: {
  usage: TurnUsage;
  workspace: ConversationWorkspace | null;
}) {
  const t = useTranslations("chat.usage");
  const tokens = usage.input_tokens + usage.output_tokens;
  const fill = fillOf(usage, workspace, t);

  return (
    <>
      <span
        className="flex items-center gap-1.5"
        title={t("inputOutputSplit", {
          input: usage.input_tokens,
          output: usage.output_tokens,
        })}
      >
        <Coins className="h-3 w-3" aria-hidden />
        {usage.cost_is_partial
          ? t("tokensAndCostPartial", { count: tokens, cost: usage.cost_usd.toFixed(4) })
          : t("tokensAndCost", { count: tokens, cost: usage.cost_usd.toFixed(4) })}
        {/* The agent's own cap first: it is the one whoever is looking at this
            agent can raise. The organization's stops every agent at once and is
            somebody else's to change, so it is only worth the space once it is
            close. */}
        {usage.agent_budget_percent !== null && (
          <span className={cn(usage.agent_budget_percent >= 80 && "text-amber-600")}>
            {t("agentShare", { percent: usage.agent_budget_percent })}
          </span>
        )}
        {usage.budget_percent !== null && usage.budget_percent >= 80 && (
          <span className="text-amber-600">{t("orgShare", { percent: usage.budget_percent })}</span>
        )}
      </span>

      {usage.context !== null && usage.context.percent !== null && (
        <ContextFill
          percent={usage.context.percent}
          resolved={usage.context.resolved}
          used={usage.context.used_tokens}
          window={usage.context.window_tokens}
        />
      )}

      {fill !== null && (
        <span className="flex items-center gap-1.5" title={fill.detail}>
          <HardDrive className="h-3 w-3" aria-hidden />
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
                {t("workspaceFull", { percent: fill.percent })}
              </span>
              {/* A bar as well as the number: 84% and 8% read the same at a
                  glance in a line of small grey text, and the whole point of
                  showing this is to be noticed before a write is refused. */}
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
      )}
    </>
  );
}
