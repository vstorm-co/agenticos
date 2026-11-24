"use client";

import { useState } from "react";
import { FolderKanban, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { ProjectPickerDialog } from "@/components/projects/project-picker-dialog";
import { useProject } from "@/hooks/use-projects";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";

/** The same share-aware project picker used by chat; the URL owns the filter. */
export function ProjectFilter({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (id: string | null) => void;
}) {
  const t = useTranslations("projects");
  const ui = useTranslations("ui");
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);
  if (!can(Perm.projectsView)) return null;
  return (
    <div className="flex gap-1 max-sm:order-last max-sm:w-full">
      <Button variant={value ? "secondary" : "outline"} onClick={() => setOpen(true)}>
        <FolderKanban aria-hidden className="size-4" />
        {value ? <SelectedProject id={value} /> : t("title")}
      </Button>
      {value && (
        <Button
          variant="ghost"
          size="icon"
          aria-label={ui("clearFilters")}
          onClick={() => onChange(null)}
        >
          <X aria-hidden />
        </Button>
      )}
      <ProjectPickerDialog
        open={open}
        onOpenChange={setOpen}
        selectedId={value}
        onPick={(project) => onChange(project?.id ?? null)}
        includeReadOnly
      />
    </div>
  );
}
function SelectedProject({ id }: { id: string }) {
  const { project } = useProject(id);
  const t = useTranslations("projects");
  return <span className="max-w-40 truncate">{project?.name ?? t("title")}</span>;
}
