"use client";

import { ProjectAvatar } from "@/components/projects/project-avatar";

import { useState } from "react";
import { Check, Plus } from "lucide-react";
import { ProjectIcon as FolderKanban } from "@/components/icons/product-icons";
import { useTranslations } from "next-intl";
import Link from "next/link";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  SearchInput,
  Skeleton,
  useDebounced,
} from "@/components/ui";
import { useProjects } from "@/hooks/use-projects";
import { ROUTES } from "@/lib/constants";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { Project } from "@/types/projects";

/**
 * Which project a new chat starts in, from the composer's `+`.
 *
 * Only projects the reader may work in: one they can only read would take the
 * first message and refuse it.
 */
export function ProjectPickerDialog({
  open,
  onOpenChange,
  selectedId,
  onPick,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  selectedId: string | null;
  onPick: (project: Project | null) => void;
}) {
  const t = useTranslations("projects");
  const [query, setQuery] = useState("");
  const search = useDebounced(query);
  // Asked when the dialog opens, not whenever a chat composer with a `+` renders.
  const { projects, isLoading } = useProjects({ search, limit: 50, enabled: open });
  const usable = projects.filter((project) => project.can_use);

  const choose = (project: Project | null) => {
    onPick(project);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_BODY, DIALOG_COLUMN, DIALOG_CONFIRM)}>
        <DialogHeader className="min-w-0 shrink-0">
          <DialogTitle className="break-words">{t("pickTitle")}</DialogTitle>
          <DialogDescription>{t("pickHint")}</DialogDescription>
        </DialogHeader>
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder={t("search")}
          className="min-w-0 shrink-0 sm:w-full"
        />
        <ul className={cn(DIALOG_BODY, "min-w-0 space-y-0.5 overscroll-contain")}>
          <li>
            <PickRow
              label={t("noProject")}
              hint={t("noProjectHint")}
              selected={selectedId === null}
              onClick={() => choose(null)}
            />
          </li>
          {isLoading ? (
            <li>
              <Skeleton className="h-12 w-full" />
            </li>
          ) : (
            usable.map((project) => (
              <li key={project.id}>
                <PickRow
                  projectName={project.name}
                  label={project.name}
                  hint={project.description ?? t("chatCount", { count: project.chat_count })}
                  selected={project.id === selectedId}
                  onClick={() => choose(project)}
                />
              </li>
            ))
          )}
        </ul>
        <Link
          href={ROUTES.PROJECTS}
          className="text-muted-foreground hover:text-foreground flex min-w-0 shrink-0 items-center gap-1.5 text-xs"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          {t("manageProjects")}
        </Link>
      </DialogContent>
    </Dialog>
  );
}

function PickRow({
  projectName,
  label,
  hint,
  selected,
  onClick,
}: {
  projectName?: string;
  label: string;
  hint: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={cn(
        "flex w-full min-w-0 items-start gap-3 rounded-lg px-2.5 py-2 text-left",
        selected ? "bg-accent" : "hover:bg-accent/60",
      )}
    >
      {projectName !== undefined ? (
        <ProjectAvatar name={projectName} size="md" />
      ) : (
        <span className="bg-muted flex size-8 shrink-0 items-center justify-center rounded-lg">
          <FolderKanban className="size-4" aria-hidden />
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 text-sm font-medium [overflow-wrap:anywhere]">{label}</span>
        <span className="text-muted-foreground line-clamp-2 text-xs [overflow-wrap:anywhere]">
          {hint}
        </span>
      </span>
      {selected && <Check className="h-4 w-4 shrink-0" aria-hidden />}
    </button>
  );
}
