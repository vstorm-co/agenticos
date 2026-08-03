"use client";

import { Coins, HardDrive } from "lucide-react";

import { cn } from "@/lib/utils";
import type { TurnUsage } from "@/types";

interface UsageStripProps {
  /** The last turn's usage, or `null` before one has been measured. */
  usage: TurnUsage | null;
}

/** Bytes as a person reads them. */
function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

/** What the workspace half is measuring, and how much of it is gone. */
function workspaceDetail(usage: TurnUsage): string | null {
  const sandbox = usage.sandbox;
  if (sandbox === null) return null;
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
export function UsageStrip({ usage }: UsageStripProps) {
  if (usage === null) return null;

  const tokens = usage.input_tokens + usage.output_tokens;
  const percent = usage.sandbox?.percent ?? null;
  const detail = workspaceDetail(usage);

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

      {usage.sandbox !== null && (
        <span className="flex items-center gap-1.5" title={detail ?? undefined}>
          <HardDrive className="h-3 w-3" aria-hidden />
          {percent === null ? (
            <span>workspace in use</span>
          ) : (
            <>
              <span
                className={cn(
                  percent >= 90 && "text-destructive",
                  percent >= 80 && percent < 90 && "text-amber-600",
                )}
              >
                workspace {percent}% full
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
                aria-label="Workspace used"
              >
                <span
                  className={cn(
                    "block h-full rounded-full",
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
