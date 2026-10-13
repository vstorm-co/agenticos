"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { useApprovals } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { toolLabel } from "@/lib/tool-catalog";
import { timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui";
import { AgentFace } from "../agent-face";
import { WidgetFrame } from "../widget-frame";
import { ShieldCheck } from "lucide-react";

import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * Tool calls parked on a person. Review links to the queue rather than
 * deciding inline - a decision deserves the arguments in full, which the
 * runs page shows and a dashboard row cannot. This card earns its place by
 * being empty.
 */
export function ApprovalsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.approvals");
  const tTime = useTranslations("time");
  const tTools = useTranslations("chat.tools");
  const locale = useLocale();
  const { approvals, total, isLoading, error, refetch } = useApprovals();

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : approvals.length === 0 ? (
        <WidgetEmptyBody
          icon={ShieldCheck}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <div className="flex h-full flex-col justify-between gap-2">
          <ul className="space-y-2">
            {approvals.slice(0, 3).map((approval) => (
              <li key={approval.id} className="flex items-center gap-3 text-sm">
                <AgentFace agentId={approval.agent_id} className="size-8" />
                <span className="min-w-0 flex-1">
                  {/* Who is asking and for what, in words: a queue of tool ids
                      (`write_memory`) with no actor is one people approve blind. */}
                  <span className="text-foreground block truncate">
                    <span className="font-medium">
                      {approval.subagent_name ?? approval.agent_name ?? t("someAgent")}
                    </span>
                    <span className="text-muted-foreground"> · </span>
                    {toolLabel(approval.tool_id, tTools)}
                  </span>
                  {approval.created_at ? (
                    <span className="text-muted-foreground block truncate text-xs">
                      {approval.triggered_by_email
                        ? t("forPerson", {
                            email: approval.triggered_by_email,
                            ago: timeAgo(approval.created_at, tTime, locale),
                          })
                        : t("waiting", { ago: timeAgo(approval.created_at, tTime, locale) })}
                    </span>
                  ) : null}
                </span>
                <Button asChild size="sm">
                  <Link href={`${ROUTES.RUNS}?tab=approvals`}>{t("review")}</Link>
                </Button>
              </li>
            ))}
          </ul>
          {total > 3 ? (
            <p className="text-muted-foreground text-xs">{t("more", { count: total - 3 })}</p>
          ) : null}
        </div>
      )}
    </WidgetFrame>
  );
}
