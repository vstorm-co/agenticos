"use client";

import Link from "next/link";
import { CircleAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { usePendingApprovals } from "@/hooks/use-pending-approvals";
import { ROUTES } from "@/lib/constants";

/** How many rows the inbox lists before it leaves the rest to the queue. */
const SHOWN = 5;

/**
 * Approvals waiting on the reader, at the top of the inbox: a workflow step or
 * an agent's tool call that stands still until somebody decides. The decision
 * itself is made in Activity → Approvals, where the controls and the details
 * are, so every row leads there.
 */
export function ApprovalsWaiting() {
  const t = useTranslations("inbox.approvals");
  const { tools, steps, count } = usePendingApprovals();
  if (count === 0) return null;
  const queue = `${ROUTES.RUNS}?tab=approvals`;
  const rows = [
    ...steps.map((step) => ({
      id: step.id,
      title: step.title,
      source: t("fromWorkflow", { workflow: step.workflow_name }),
    })),
    ...tools.map((call) => ({
      id: call.id,
      title: t("toolCall", { tool: call.tool_id }),
      source: call.agent_name ? t("fromAgent", { agent: call.agent_name }) : t("anAgent"),
    })),
  ].slice(0, SHOWN);
  return (
    <section aria-labelledby="inbox-approvals" className="border-b">
      <div className="flex flex-wrap items-center gap-2 px-5 pt-4 pb-2">
        <CircleAlert className="text-warning size-4 shrink-0" aria-hidden />
        <h2 id="inbox-approvals" className="text-sm font-semibold">
          {t("title", { count })}
        </h2>
        <Link
          href={queue}
          className="text-muted-foreground hover:text-foreground ml-auto text-sm underline underline-offset-4"
        >
          {t("open")}
        </Link>
      </div>
      <ul className="pb-3">
        {rows.map((row) => (
          <li key={row.id}>
            <Link
              href={queue}
              className="hover:bg-foreground/5 flex min-w-0 flex-col px-5 py-2 max-md:min-h-11"
            >
              <span className="truncate text-sm font-medium">{row.title}</span>
              <span className="text-muted-foreground truncate text-xs">{row.source}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
