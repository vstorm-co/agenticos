"use client";

import { FolderKanban, MessageSquare } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";

import { AudienceChip } from "@/components/sharing/audience-chip";
import { Card } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import type { Project } from "@/types/projects";

/**
 * One project in the grid: what it is for, how many of the reader's chats it
 * holds, the agent a new chat starts with, and who else works in it.
 */
export function ProjectCard({ project }: { project: Project }) {
  const t = useTranslations("projects");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const active = project.last_active_at ?? project.updated_at ?? project.created_at;
  return (
    <Card className="group hover:border-foreground/20 relative h-full transition-colors">
      <Link
        href={ROUTES.PROJECT_DETAIL(project.id)}
        className="flex h-full flex-col gap-3 rounded-[inherit] p-4 focus-visible:outline-offset-[-2px]"
      >
        <span className="flex items-center gap-3">
          <span className="bg-muted text-foreground flex h-10 w-10 shrink-0 items-center justify-center rounded-xl">
            <FolderKanban className="h-5 w-5" aria-hidden />
          </span>
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium">{project.name}</span>
            {active !== null && (
              <span className="text-muted-foreground block text-xs">
                {t("activeWhen", { when: timeAgo(active, tTime, locale) })}
              </span>
            )}
          </span>
        </span>
        {project.description && (
          <span className="text-muted-foreground line-clamp-2 text-sm">{project.description}</span>
        )}
        <span className="text-muted-foreground mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="flex items-center gap-1">
            <MessageSquare className="h-3.5 w-3.5" aria-hidden />
            {t("chatCount", { count: project.chat_count })}
          </span>
          {project.default_agent_name && (
            <span className="truncate">
              {t("startsWith", { agent: project.default_agent_name })}
            </span>
          )}
          <AudienceChip visibility={project.visibility} groups={project.shared_groups} />
        </span>
      </Link>
    </Card>
  );
}
