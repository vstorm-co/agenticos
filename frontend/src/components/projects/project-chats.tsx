"use client";

import Link from "next/link";
import { MessageSquare, Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import { Button, ListCard, ListCardEmpty } from "@/components/ui";
import { useProjectChats } from "@/hooks/use-projects";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import type { Project } from "@/types/projects";

/**
 * The reader's chats in the project, and a new one.
 *
 * Their own only: a project shares its files and instructions, and a person's
 * conversations in it stay theirs, as everywhere else.
 */
export function ProjectChats({ project }: { project: Project }) {
  const t = useTranslations("projects");
  const tTime = useTranslations("time");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const { chats, total, isLoading, error } = useProjectChats(project.id);

  const newChat = project.can_use ? (
    <Button asChild size="sm">
      <Link href={ROUTES.PROJECT_CHAT(project.id)} data-tour="project-new-chat">
        <Plus className="h-4 w-4" />
        {t("newChat")}
      </Link>
    </Button>
  ) : undefined;

  return (
    <ListCard
      title={t("chats")}
      counted={error ? null : t("chatCount", { count: total })}
      controls={newChat}
      empty={!isLoading && !error && total === 0}
    >
      {isLoading ? (
        <LoadingState variant="skeleton-list" rows={3} />
      ) : error ? (
        <ErrorState description={getErrorMessage(error, tErrors)} />
      ) : chats.length === 0 ? (
        <ListCardEmpty
          icon={MessageSquare}
          title={t("noChatsYet")}
          description={project.can_use ? t("noChatsHint") : t("noChatsViewer")}
        />
      ) : (
        <ul className="divide-border divide-y">
          {chats.map((chat) => (
            <li key={chat.id}>
              <Link
                href={`${ROUTES.CHAT}?id=${chat.id}`}
                className="hover:bg-accent/60 flex items-center gap-3 rounded-lg px-2 py-2.5"
              >
                <MessageSquare className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
                <span className="min-w-0 flex-1 truncate text-sm">
                  {chat.title || t("untitledChat")}
                </span>
                {chat.agents?.[0] && (
                  <span className="text-muted-foreground hidden truncate text-xs sm:block">
                    {chat.agents[0].name}
                  </span>
                )}
                <span className="text-muted-foreground shrink-0 text-xs">
                  {timeAgo(chat.updated_at ?? chat.created_at, tTime, locale)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </ListCard>
  );
}
