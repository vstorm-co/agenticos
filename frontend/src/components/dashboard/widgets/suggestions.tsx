"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { useWaitingSuggestions } from "@/hooks/use-authoring";
import { ROUTES } from "@/lib/constants";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * What the authoring assistant suggested and nobody has decided: per agent the
 * reader may edit, how many changes to its instructions, tools and configuration
 * wait, and how many skill and context file changes - each one click from where
 * it is decided.
 */
export function SuggestionsWidget({ title, hint, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.suggestions");
  const { waiting, isLoading, error, refetch } = useWaitingSuggestions();
  const agents = waiting?.agents ?? [];
  const skills = waiting?.skills ?? 0;
  const contexts = waiting?.contexts ?? 0;

  return (
    <WidgetFrame title={title} hint={hint} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : agents.length === 0 && skills === 0 && contexts === 0 ? (
        <WidgetEmptyBody
          icon={Sparkles}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="divide-border divide-y text-sm">
          {agents.map((row) => (
            <li key={row.agent_id} className="flex items-center justify-between gap-3 py-2">
              <Link
                href={`${ROUTES.AGENTS}/${row.agent_id}?tab=build`}
                className="truncate font-medium"
              >
                {row.name}
              </Link>
              <span className="text-muted-foreground shrink-0 text-xs">
                {t("counts", {
                  instructions: row.instructions,
                  tools: row.tools,
                  fields: row.fields ?? 0,
                })}
              </span>
            </li>
          ))}
          {skills > 0 && (
            <li className="py-2">
              <Link href={ROUTES.SKILLS} className="font-medium">
                {t("skills", { count: skills })}
              </Link>
            </li>
          )}
          {contexts > 0 && (
            <li className="py-2">
              <Link href={ROUTES.CONTEXT} className="font-medium">
                {t("contexts", { count: contexts })}
              </Link>
            </li>
          )}
        </ul>
      )}
    </WidgetFrame>
  );
}
