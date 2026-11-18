"use client";

import Link from "next/link";
import { ChevronRight, Workflow } from "lucide-react";
import { useTranslations } from "next-intl";

import { ToolMark, useActionPhrase } from "@/components/runs/approval-request";
import { usePendingApprovals } from "@/hooks/use-pending-approvals";
import { approvalSummary } from "@/lib/agent-step-captions";
import { callSummary } from "@/lib/approval-view";
import { ROUTES } from "@/lib/constants";

/** The inbox previews the queue; decisions stay on its full, authorized details. */
const SHOWN = 5;

export function ApprovalsWaiting() {
  const t = useTranslations("inbox.approvals");
  const tTools = useTranslations("chat.tools");
  const phrase = useActionPhrase();
  const { tools, steps } = usePendingApprovals();
  const queue = `${ROUTES.RUNS}?tab=approvals`;
  const rows = [
    ...steps.map((step) => ({
      id: `step:${step.id}`,
      title: step.title,
      detail: null,
      source: t("fromWorkflow", { workflow: step.workflow_name }),
      mark: (
        <span className="bg-muted/50 flex size-8 shrink-0 items-center justify-center rounded-lg">
          <Workflow className="text-muted-foreground size-4" aria-hidden />
        </span>
      ),
    })),
    ...tools.map((call) => {
      const action = phrase(call.tool_id);
      const summary = call.content_hidden
        ? null
        : (approvalSummary(call.capability_tool_id, call.context, tTools) ??
          callSummary(call.tool_args));
      return {
        id: `tool:${call.id}`,
        title: action,
        detail: summary,
        source: call.agent_name ? t("fromAgent", { agent: call.agent_name }) : t("anAgent"),
        mark: <ToolMark toolName={call.tool_id} className="bg-muted/50 border-0" />,
      };
    }),
  ].slice(0, SHOWN);
  return (
    <section aria-labelledby="inbox-approvals" className="border-b last:border-b-0">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4 pb-2 sm:px-5">
        <h2 id="inbox-approvals" className="text-muted-foreground text-xs font-medium">
          {t("title")}
        </h2>
        <Link
          href={queue}
          className="text-muted-foreground hover:text-foreground touch:min-h-11 inline-flex min-h-6 items-center gap-1 rounded-sm text-xs focus-visible:outline-2 focus-visible:outline-offset-4"
        >
          {t("open")}
          <ChevronRight className="size-3.5" aria-hidden />
        </Link>
      </div>
      <ul className="space-y-1 px-2 pb-3 sm:px-3">
        {rows.map((row) => (
          <li key={row.id}>
            <Link
              href={queue}
              className="group hover:bg-muted/40 focus-visible:bg-muted/40 flex min-h-16 items-start gap-3 rounded-xl px-2 py-3 outline-offset-[-2px] transition-colors motion-reduce:transition-none"
            >
              {row.mark}
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="text-sm leading-5 font-medium wrap-anywhere">{row.title}</span>
                {row.detail && (
                  <span className="text-foreground/80 line-clamp-2 text-sm leading-5 wrap-anywhere">
                    {row.detail}
                  </span>
                )}
                <span className="text-muted-foreground text-xs wrap-anywhere">{row.source}</span>
              </span>
              <ChevronRight
                className="text-muted-foreground/60 group-hover:text-foreground mt-1 size-4 shrink-0"
                aria-hidden
              />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
