"use client";

import Link from "next/link";
import { SearchX } from "lucide-react";
import { useTranslations } from "next-intl";

import { useKnowledgeGaps } from "@/hooks/use-knowledge-gaps";
import { ROUTES } from "@/lib/constants";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many a card lists; each knowledge base's own tab has the rest. */
const SHOWN = 5;

/**
 * The open topics asked most often, across every knowledge base the caller
 * reads - what agents went looking for and did not find. Each row opens the
 * knowledge base it belongs to, on its gaps tab.
 */
export function KnowledgeGapsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.knowledge-gaps");
  const { topics, isLoading, error, refetch } = useKnowledgeGaps(
    { kind: "organization" },
    { status: "open", limit: SHOWN },
  );

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : topics.length === 0 ? (
        <WidgetEmptyBody
          icon={SearchX}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="divide-border divide-y">
          {topics.map((topic) => (
            <li key={topic.id}>
              <Link
                href={`${ROUTES.RAG}/${topic.knowledge_base_id}?tab=gaps`}
                className="hover:bg-accent/40 flex items-center justify-between gap-3 rounded-md px-1 py-2"
              >
                <span className="min-w-0">
                  <span className="text-foreground block truncate text-sm">{topic.label}</span>
                  <span className="text-muted-foreground block truncate text-xs">
                    {topic.knowledge_base_name}
                  </span>
                </span>
                <span className="text-muted-foreground shrink-0 text-xs">
                  {t("asked", { count: topic.question_count })}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}
