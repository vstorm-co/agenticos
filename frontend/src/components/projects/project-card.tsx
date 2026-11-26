"use client";

import { ProjectAvatar } from "@/components/projects/project-avatar";

import { ChatIcon as MessageSquare } from "@/components/icons/product-icons";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { AudienceChip } from "@/components/sharing/audience-chip";
import {
  ResourceCard,
  ResourceCardHeader,
  ResourceCardDescription,
  ResourceCardFooter,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { Project } from "@/types/projects";

/**
 * One project in the grid: what it is for, how many of the reader's chats it
 * holds, the agent a new chat starts with, and who else works in it.
 */
export function ProjectCard({ project }: { project: Project }) {
  const t = useTranslations("projects");
  return (
    <ResourceCard className="min-h-52 p-0">
      <Link
        href={ROUTES.PROJECT_DETAIL(project.id)}
        className="flex h-full flex-1 flex-col rounded-[inherit] p-5 focus-visible:outline-offset-[-2px]"
      >
        <ResourceCardHeader>
          <ProjectAvatar name={project.name} size="lg" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <p className="line-clamp-2 font-semibold break-words">{project.name}</p>
            <AudienceChip visibility={project.visibility} groups={project.shared_groups} />
          </div>
        </ResourceCardHeader>
        <ResourceCardDescription className="my-4 line-clamp-2">
          {project.description}
        </ResourceCardDescription>
        <ResourceCardFooter className="text-muted-foreground border-0 pt-0 text-xs">
          <span className="flex items-center gap-1">
            <MessageSquare className="size-3.5" aria-hidden />
            {t("chatCount", { count: project.chat_count })}
          </span>
          {project.default_agent_name && (
            <span className="min-w-0 truncate">
              {t("startsWith", { agent: project.default_agent_name })}
            </span>
          )}
        </ResourceCardFooter>
      </Link>
    </ResourceCard>
  );
}
