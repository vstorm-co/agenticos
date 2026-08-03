"use client";

import { Coins, HardDrive } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { ConversationWorkspace } from "@/lib/conversation-workspace-api";
import type { TurnUsage } from "@/types";

interface UsageStripProps {
  /** The last turn's usage, or `null` before one has been measured. */
  usage: TurnUsage | null;
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
  detail: string | null;
}

/** How full the workspace is, from whichever source can say. */
function fillOf(usage: TurnUsage, workspace: ConversationWorkspace | null): Fill | null {
  const sandbox = usage.sandbox;
  if (sandbox !== null) return { percent: sandbox.percent, detail: reportedDetail(sandbox) };
  // No turn has reported one - a reopened conversation. A stored workspace can still
  // be measured from the listing; a container cannot, and "in use" would claim a
  // sandbox is running when the last one may have been reaped weeks ago.
  if (workspace === null || workspace.backend !== "state" || workspace.bytes_limit === null)
    return null;
  return {
    percent: Math.round((workspace.bytes_total * 100) / workspace.bytes_limit),
    detail: `${size(workspace.bytes_total)} of ${size(workspace.bytes_limit)} stored`,
  };
}

/** Bytes as a person reads them. */
function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

/** What the workspace half is measuring, and how much of it is gone. */
function reportedDetail(sandbox: NonNullable<TurnUsage["sandbox"]>): string | null {
  if (sandbox.bytes_used !== null && sandbox.bytes_limit !== null)
    return `${size(sandbox.bytes_used)} of ${size(sandbox.bytes_limit)} stored`;
  if (sandbox.memory_bytes !== null && sandbox.memory_limit_bytes !== null)
    return `${size(sandbox.memory_bytes)} of ${size(sandbox.memory_limit_bytes)} in the container`;
  return "in use — this host did not report a number";
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
 */
export function UsageStrip({ usage, workspace = null }: UsageStripProps) {
  const t = useTranslations("chat.usage");
  if (usage === null) return null;

  const tokens = usage.input_tokens + usage.output_tokens;
  const fill = fillOf(usage, workspace);
  const percent = fill?.percent ?? null;
  const detail = fill?.detail ?? null;

  return (
    <div className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-xs">
      <span
        className="flex items-center gap-1.5"
        title={`${usage.input_tokens.toLocaleString()} in · ${usage.output_tokens.toLocaleString()} out`}
      >
        <Coins className="h-3 w-3" aria-hidden />
        {tokens.toLocaleString()} tokens · ${usage.cost_usd.toFixed(4)}
        {/* The agent's own cap first: it is the one whoever is looking at this
            agent can raise. The organization's stops every agent at once and is
            somebody else's to change, so it is only worth the space once it is
            close. */}
        {usage.agent_budget_percent !== null && (
          <span className={cn(usage.agent_budget_percent >= 80 && "text-amber-600")}>
            · {usage.agent_budget_percent}% of this agent&apos;s month
          </span>
        )}
        {usage.budget_percent !== null && usage.budget_percent >= 80 && (
          <span className="text-amber-600">
            · {usage.budget_percent}% of the organization&apos;s
          </span>
        )}
      </span>

      {fill !== null && (
        <span className="flex items-center gap-1.5" title={detail ?? undefined}>
          <HardDrive className="h-3 w-3" aria-hidden />
          {percent === null ? (
            <span>{t("workspaceInUse")}</span>
          ) : (
            <>
              <span
                className={cn(
                  percent >= 90 && "text-destructive",
                  percent >= 80 && percent < 90 && "text-amber-600",
                )}
              >
                {t("workspaceFull", { percent })}
              </span>
              {/* A bar as well as the number: 84% and 8% read the same at a
                  glance in a line of small grey text, and the whole point of
                  showing this is to be noticed before a write is refused. */}
              <span
                className="bg-muted h-1 w-16 overflow-hidden rounded-full"
                role="progressbar"
                aria-valuenow={percent}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={t("workspaceUsed")}
              >
                <span
                  className={cn(
                    t("blockHFullRounded"),
                    percent >= 90
                      ? "bg-destructive"
                      : percent >= 80
                        ? "bg-amber-500"
                        : "bg-foreground/40",
                  )}
                  style={{ width: `${Math.min(100, percent)}%` }}
                />
              </span>
            </>
          )}
        </span>
      )}
    </div>
  );
}
