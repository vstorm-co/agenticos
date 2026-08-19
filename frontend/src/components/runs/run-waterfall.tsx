"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { ManifestRequest } from "@/types/runs";

/**
 * Every model request the run made, as bars against the longest one.
 *
 * A run is one row with one duration, and forty seconds is either one slow
 * request or nine quick ones with eight tool calls between them. Those are
 * opposite problems - a provider having a bad minute, and an agent thrashing
 * through a tool loop - and the run row cannot tell them apart. This can.
 *
 * The bar is scaled to the slowest request rather than to the run's wall clock,
 * because the gaps between requests are tool executions rather than model time,
 * and a bar that included them would attribute a slow database query to the
 * model. What is being compared here is requests with each other.
 *
 * A request that raised is drawn in the failure colour with its exception class,
 * because it is the entry an operator is looking for: a run that died on its
 * fourth request and one that died on its first are the same red row otherwise.
 */
export function RunWaterfall({ requests }: { requests: ManifestRequest[] }) {
  const t = useTranslations("pages.runs");
  if (requests.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("noRequestsRecorded")}</p>;
  }
  // Never zero: every duration being zero would divide by it, and a run of
  // sub-millisecond requests is a mocked model rather than an impossibility.
  const slowest = Math.max(...requests.map((request) => request.duration_ms), 1);

  return (
    <ol className="space-y-1">
      {requests.map((request) => (
        <li key={request.index} className="grid grid-cols-[2rem_1fr_auto] items-center gap-2">
          <span className="text-muted-foreground font-mono text-[11px] tabular-nums">
            {t("requestIndex", { index: request.index + 1 })}
          </span>
          <div className="bg-muted/40 h-5 overflow-hidden rounded">
            <div
              className={cn(
                "flex h-full items-center rounded px-1.5",
                request.failed === null ? "bg-primary/25" : "bg-destructive/30",
              )}
              style={{ width: `${Math.max((request.duration_ms / slowest) * 100, 4)}%` }}
            >
              <span className="truncate font-mono text-[10px] whitespace-nowrap">
                {request.failed ?? request.tool_calls.join(", ")}
              </span>
            </div>
          </div>
          <span
            className="text-muted-foreground font-mono text-[10px] tabular-nums"
            title={t("requestDetail", {
              input: request.input_tokens,
              output: request.output_tokens,
              messages: request.message_count,
              finish: request.finish_reason ?? "-",
            })}
          >
            {t("milliseconds", { ms: request.duration_ms })}
          </span>
        </li>
      ))}
    </ol>
  );
}
