"use client";

import { Users } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { ShareResourceButton } from "@/components/sharing/share-resource-button";
import { useProject } from "@/hooks/use-projects";
import { ROUTES } from "@/lib/constants";
import { useAuthStore } from "@/stores";
import type { ChatPerson } from "@/types/conversation";
import { PersonFace } from "./person-face";

export function TeamRoomHeader({
  projectId,
  present,
}: {
  projectId: string;
  present: ChatPerson[];
}) {
  const t = useTranslations("chat.teamRoom");
  const { project } = useProject(projectId);
  const me = useAuthStore((state) => state.user?.id);
  const others = present.filter((person) => person.user_id !== me);
  return (
    <div
      data-tour="chat-team-room"
      className="bg-background/90 border-border/60 sticky top-2 z-20 mb-4 flex items-center gap-3 rounded-xl border p-3 backdrop-blur"
    >
      <Users className="text-muted-foreground size-5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <Link href={ROUTES.PROJECT_DETAIL(projectId)} className="text-sm font-medium">
          {project ? t("titleInProject", { name: project.name }) : t("title")}
        </Link>
        <p className="text-muted-foreground text-xs">{t("audience")}</p>
        <p className="text-muted-foreground mt-1 text-xs" role="status">
          {others.length === 0
            ? t("alone")
            : t("here", {
                count: others.length,
                names: others.map((person) => person.name).join(", "),
              })}
        </p>
      </div>
      <span className="hidden shrink-0 items-center -space-x-1.5 sm:flex" aria-hidden>
        {others.slice(0, 3).map((person) => (
          <PersonFace
            key={person.user_id}
            person={person}
            className="ring-background size-6 ring-2"
          />
        ))}
      </span>
      {project && (
        <ShareResourceButton
          resourceType="project"
          resourceId={project.id}
          name={project.name}
          canManage={project.can_edit}
          compact
          className="h-8 shrink-0 text-xs"
        />
      )}
    </div>
  );
}

export function TeamRoomEmpty() {
  const t = useTranslations("chat.teamRoom");
  return (
    <div className="mx-auto max-w-md px-4 py-12 text-center">
      <Users className="text-muted-foreground mx-auto mb-3 size-7" aria-hidden />
      <h2 className="text-lg font-medium">{t("emptyTitle")}</h2>
      <p className="text-muted-foreground mt-2 text-sm leading-relaxed">{t("emptyDescription")}</p>
    </div>
  );
}
