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

/** One row of tiles; the page behind "see all" has the rest. */
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
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 2xl:grid-cols-4">
          {projects.map((project) => {
            const active = project.last_active_at ?? project.updated_at ?? project.created_at;
            return (
              <li key={project.id}>
                <Link
                  href={ROUTES.PROJECT_DETAIL(project.id)}
                  className="group border-foreground/8 hover:bg-accent/40 flex h-full flex-col gap-3 rounded-xl border p-4 transition-colors"
                >
                  <span className="flex w-full min-w-0 items-center gap-2.5">
                    <FolderKanban className="text-muted-foreground h-5 w-5 shrink-0" aria-hidden />
                    <span className="min-w-0 flex-1 truncate text-sm font-semibold">
                      {project.name}
                    </span>
                    <ArrowUpRight className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
                  </span>
                  {project.description && (
                    <span className="text-muted-foreground line-clamp-2 text-xs leading-relaxed">
                      {project.description}
                    </span>
                  )}
                  <span className="mt-auto w-full min-w-0">
                    <span className="text-muted-foreground flex items-center gap-1 text-xs">
                      <MessageSquare className="h-3 w-3 shrink-0" aria-hidden />
                      <span className="truncate">
                        {tProjects("chatCount", { count: project.chat_count })}
                        {active !== null && ` · ${timeAgo(active, tTime, locale)}`}
                      </span>
                    </span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </WidgetFrame>
  );
}
