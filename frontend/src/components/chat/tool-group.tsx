"use client";

import { toolLookupName } from "@/lib/tool-identity";

import { createElement, type ReactNode } from "react";
import { ChevronRight, LoaderCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { toolIcon } from "@/lib/step-icons";
import { toolStep, type McpServerRef } from "@/lib/tool-steps";
import type { ToolCall } from "@/types";

/** Consecutive calls share one quiet row; agent messages delimit the groups. */
export function ToolGroup({
  calls,
  mcpServers,
  children,
}: {
  calls: readonly ToolCall[];
  mcpServers: McpServerRef[];
  children: ReactNode;
}) {
  const t = useTranslations("chat.steps");
  const tTools = useTranslations("chat.tools");
  const runText = useTranslations("pages.runs");
  if (calls.length < 2) return children;
  const finished = calls.every((call) => call.status === "completed");
  const steps = calls.map((call) =>
    toolStep(call.name, call.args, finished, tTools, mcpServers, call),
  );
  const labels = [...new Set(steps.map((step) => step.label))];
  const Icon = toolIcon(
    steps[0]!.kind === "mcp" ? calls[0]!.name : toolLookupName(calls[0]!),
    steps[0]!.kind,
  );
  const running = calls.some((call) => call.status === "running" || call.status === "pending");
  const status = calls.some((call) => call.status === "awaiting_answer")
    ? "awaiting_answer"
    : calls.some((call) => call.status === "awaiting_approval")
      ? "awaiting_approval"
      : calls.some((call) => call.status === "error")
        ? "error"
        : undefined;
  return (
    <details className="group/tool-group min-w-0 text-[13px]">
      <summary className="text-muted-foreground hover:text-foreground flex min-h-8 cursor-pointer items-center gap-2 rounded-md py-1 focus-visible:outline-2 focus-visible:outline-offset-2">
        <span className="flex size-5 shrink-0 items-center justify-center" aria-hidden>
          {running ? (
            <LoaderCircle className="text-foreground size-3.5 motion-safe:animate-spin" />
          ) : (
            createElement(Icon, { className: "size-3.5" })
          )}
        </span>
        <span className="min-w-0 truncate" title={labels.join(", ")}>
          {labels.slice(0, 3).join(", ")}
          {labels.length > 3 && "…"}
        </span>
        <span className="shrink-0 text-xs tabular-nums">
          {t("activityCount", { count: calls.length })}
        </span>
        {status && <span className="text-xs">{runText("toolState", { status })}</span>}
        {running && <span className="sr-only">{t("running")}</span>}
        <ChevronRight
          aria-hidden
          className="size-3.5 shrink-0 opacity-50 transition-transform group-open/tool-group:rotate-90"
        />
      </summary>
      <div className="mt-1 pl-2">{children}</div>
    </details>
  );
}
