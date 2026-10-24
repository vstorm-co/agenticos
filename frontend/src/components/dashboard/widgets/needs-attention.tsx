"use client";

import Link from "next/link";
import { CircleCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { ImproveLink } from "@/components/agents/improve-link";
import { Button } from "@/components/ui";
import { useAgentAttention } from "@/hooks";
import { attentionParts } from "@/lib/attention";
import { ROUTES } from "@/lib/constants";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many a card lists; the agents with the most come first. */
const SHOWN = 5;

/**
 * The agents to look at in the period: answers rated down, their own runs
 * failed, an eval suite failing - each with what it counts, and Improve for
 * whoever may edit it. Counts only; what was said stays with each run.
 */
export function NeedsAttentionWidget({ title, hint, period, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.needs-attention");
  const tParts = useTranslations("attention");
  const { agents, isLoading, error, refetch } = useAgentAttention({
    from: period.from,
    to: period.to,
  });

  return (
    <WidgetFrame title={title} hint={hint} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : agents.length === 0 ? (
        <WidgetEmptyBody
          icon={CircleCheck}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="divide-border divide-y text-sm">
          {agents.slice(0, SHOWN).map((item) => (
            <li key={item.agent_id} className="flex items-center justify-between gap-3 py-2">
              <span className="min-w-0 space-y-0.5">
                <Link
                  href={ROUTES.AGENT_DETAIL(item.agent_id)}
                  className="block truncate font-medium"
                >
                  {item.name}
                </Link>
                <span className="text-muted-foreground block truncate text-xs">
                  {attentionParts(item, tParts).join(" · ")}
                </span>
              </span>
              {item.can_edit && (
                <Button asChild size="sm" variant="outline" className="shrink-0">
                  <ImproveLink agentId={item.agent_id}>{t("improve")}</ImproveLink>
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}
