"use client";

import Link from "next/link";
import { ArrowUpRight, FolderKanban, MessageSquare } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { useProjects } from "@/hooks/use-projects";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** The most recent projects; the page behind "see all" has the rest. */
const SHOWN = 4;

/**
 * The reader's projects, most recently changed first: where their ongoing work
 * is, and a click from a new chat in it.
 */
export function ProjectsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.projects");
  const tProjects = useTranslations("projects");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { projects, isLoading, error, refetch } = useProjects({ limit: SHOWN });

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : projects.length === 0 ? (
        <WidgetEmptyBody
          icon={FolderKanban}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="grid grid-cols-1 gap-x-6 gap-y-2 @[40rem]/widget:grid-cols-2">
          {projects.map((project) => {
            const active = project.last_active_at ?? project.updated_at ?? project.created_at;
            return (
              <li key={project.id}>
                <Link
                  href={ROUTES.PROJECT_DETAIL(project.id)}
                  className="hover:bg-muted/60 focus-visible:ring-ring group flex h-full items-start gap-3 rounded-lg px-1 py-2.5 transition-colors outline-none focus-visible:ring-2"
                >
                  <span
                    className="bg-foreground/[0.04] text-muted-foreground flex size-9 shrink-0 items-center justify-center rounded-lg"
                    aria-hidden
                  >
                    <FolderKanban className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1 space-y-1">
                    <span className="text-foreground block truncate text-sm font-medium">
                      {project.name}
                    </span>
                    {project.description && (
                      <span className="text-muted-foreground line-clamp-2 text-xs leading-relaxed">
                        {project.description}
                      </span>
                    )}
                    <span className="text-muted-foreground flex items-center gap-1 text-xs">
                      <MessageSquare className="size-3 shrink-0" aria-hidden />
                      <span className="truncate">
                        {tProjects("chatCount", { count: project.chat_count })}
                        {active !== null && ` · ${timeAgo(active, tTime, locale)}`}
                      </span>
                    </span>
                  </span>
                  <ArrowUpRight
                    className="text-muted-foreground mt-0.5 size-3.5 shrink-0"
                    aria-hidden
                  />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </WidgetFrame>
  );
}
