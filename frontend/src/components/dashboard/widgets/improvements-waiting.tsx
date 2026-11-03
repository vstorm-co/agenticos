"use client";

import Link from "next/link";
import { CircleCheck, TrendingUp } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useImprovementsAwaiting } from "@/hooks/use-improvements";
import { useSkillImprovementsAwaiting } from "@/hooks/use-skill-improvement";
import { ROUTES } from "@/lib/constants";
import { stopOf } from "@/lib/improvement-steps";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many a card lists; the newest come first. */
const SHOWN = 5;

/** One waiting session, an agent's or a skill's, as the card lists it. */
interface Waiting {
  id: string;
  name: string;
  href: string;
  openHref: string;
  what: string;
  createdAt: string;
}

/**
 * Improvement sessions waiting for a person - an agent's or a skill's: stopped after
 * a step, or with a result to review. Each opens its session at the step that waits.
 * The two are read apart, so one that fails leaves the other listed.
 */
export function ImprovementsWaitingWidget({ title, hint, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.improvements-waiting");
  const tErrors = useTranslations("dashboard.errors");
  const agents = useImprovementsAwaiting();
  const skills = useSkillImprovementsAwaiting();
  const isLoading = agents.isLoading || skills.isLoading;
  const failed = agents.error ? (skills.error ? "both" : "agents") : skills.error ? "skills" : null;
  const refetch = () => Promise.all([agents.refetch(), skills.refetch()]);
  const what = (item: Parameters<typeof stopOf>[0] & { next_step_blocked?: unknown }) =>
    t(item.next_step_blocked ? "what.blocked" : `what.${stopOf(item) ?? "result"}`);
  const sessions: Waiting[] = [
    ...(agents.error ? [] : agents.sessions).map((item) => ({
      id: item.id,
      name: item.agent_name,
      href: ROUTES.AGENT_DETAIL(item.agent_id),
      openHref: `${ROUTES.AGENT_DETAIL(item.agent_id)}/improve/${item.id}`,
      what: what(item),
      createdAt: item.created_at,
    })),
    ...(skills.error ? [] : skills.sessions).map((item) => ({
      id: item.id,
      name: t("skill", {
        name: item.skill_name,
        kind: item.fork_id === null ? "main" : "fork",
        line: item.line_name,
      }),
      href: ROUTES.SKILL_DETAIL(item.skill_id),
      openHref: `${ROUTES.SKILL_DETAIL(item.skill_id)}/improve/${item.id}`,
      what: what(item),
      createdAt: item.created_at,
    })),
  ].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  return (
    <WidgetFrame title={title} hint={hint} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : failed === "both" ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : sessions.length === 0 ? (
        <WidgetEmptyBody
          icon={CircleCheck}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="divide-border divide-y text-sm">
          {sessions.slice(0, SHOWN).map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-3 py-2">
              <span className="min-w-0 space-y-0.5">
                <Link href={item.href} className="block truncate font-medium">
                  {item.name}
                </Link>
                <span className="text-muted-foreground block truncate text-xs">{item.what}</span>
              </span>
              <Button asChild size="sm" variant="outline" className="shrink-0">
                <Link href={item.openHref}>
                  <TrendingUp className="h-4 w-4" aria-hidden />
                  {t("open")}
                </Link>
              </Button>
            </li>
          ))}
        </ul>
      )}
      {!isLoading && (failed === "agents" || failed === "skills") && (
        <p role="alert" className="text-muted-foreground flex items-center gap-2 text-xs">
          {t("partial", { failed })}
          <Button variant="link" size="sm" className="h-auto p-0" onClick={() => refetch()}>
            {tErrors("retry")}
          </Button>
        </p>
      )}
    </WidgetFrame>
  );
}
