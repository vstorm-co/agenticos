"use client";

import { ProjectAvatar } from "@/components/projects/project-avatar";

import { useState } from "react";
import { Check, Plus, ArrowUpRight } from "lucide-react";
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
import { ErrorState } from "@/components/states/error-state";
import { getErrorMessage } from "@/lib/api-error";

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
  includeReadOnly = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  selectedId: string | null;
  onPick: (project: Project | null) => void;
  includeReadOnly?: boolean;
}) {
  const t = useTranslations("projects");
  const common = useTranslations("common");
  const errors = useTranslations("errors");
  const [query, setQuery] = useState("");
  const search = useDebounced(query);
  // Asked when the dialog opens, not whenever a chat composer with a `+` renders.
  const { projects, isLoading, error, refetch } = useProjects({ search, limit: 50, enabled: open });
  const usable = projects.filter((project) => includeReadOnly || project.can_use);

  const choose = (project: Project | null) => {
    onPick(project);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_BODY, DIALOG_COLUMN, DIALOG_CONFIRM)}>
        <DialogHeader className="min-w-0 shrink-0 pr-6">
          <DialogTitle className="text-base font-medium break-words">
            {t(includeReadOnly ? "title" : "pickTitle")}
          </DialogTitle>
          <DialogDescription>
            {t(includeReadOnly ? "resources.filterHint" : "pickHint")}
          </DialogDescription>
        </DialogHeader>
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder={t("search")}
          className="min-w-0 shrink-0 sm:w-full"
        />
        <ul className={cn(DIALOG_BODY, "min-h-48 min-w-0 space-y-1 overscroll-contain")}>
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
          ) : error ? (
            <li>
              <ErrorState
                description={getErrorMessage(error, errors)}
                cta={{ label: common("retry"), onClick: () => void refetch() }}
                className="border-0 px-3 py-4"
              />
            </li>
          ) : usable.length === 0 ? (
            <li className="text-muted-foreground flex min-h-28 items-center justify-center px-5 py-6 text-center text-sm leading-6">
              {t(search.trim() ? "pickNoMatches" : "pickEmpty")}
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
          onClick={() => onOpenChange(false)}
          className="text-brand border-border flex min-h-9 min-w-0 shrink-0 items-center gap-2 border-t pt-3 text-xs underline-offset-4 hover:underline"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          {t("manageProjects")}
          <ArrowUpRight className="ml-auto size-3.5" aria-hidden />
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
        "focus-visible:ring-ring flex w-full min-w-0 items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-inset",
        selected ? "bg-control" : "hover:bg-muted",
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
