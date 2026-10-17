"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { useRouter } from "@/lib/locale-navigation";
import {
  Button,
  Card,
  CardContent,
  ConfirmDialog,
  FormField,
  Input,
  Textarea,
} from "@/components/ui";
import { useProject } from "@/hooks/use-projects";
import { ROUTES } from "@/lib/constants";
import type { Project } from "@/types/projects";
import { DefaultAgentSelect } from "./default-agent-select";

/**
 * What the project is and what every agent in it is told.
 *
 * Read-only to whoever may not change it - the instructions are worth reading
 * for anybody working in the project, since they shape every answer in it.
 */
export function ProjectSettings({ project }: { project: Project }) {
  const t = useTranslations("projects");
  const router = useRouter();
  const { update, remove } = useProject(project.id);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [instructions, setInstructions] = useState(project.instructions);
  const [agentId, setAgentId] = useState(project.default_agent_id);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const editable = project.can_edit;
  const changed =
    name !== project.name ||
    description !== (project.description ?? "") ||
    instructions !== project.instructions ||
    agentId !== project.default_agent_id;

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-4 pt-6">
          <FormField label={t("name")} htmlFor="project-name">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={120}
              disabled={!editable}
            />
          </FormField>
          <FormField label={t("description")} htmlFor="project-description">
            <Input
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              maxLength={500}
              disabled={!editable}
            />
          </FormField>
          <FormField
            label={t("defaultAgent")}
            htmlFor="project-agent"
            description={t("defaultAgentHint")}
          >
            <DefaultAgentSelect
              id="project-agent"
              value={agentId}
              onChange={setAgentId}
              disabled={!editable}
            />
          </FormField>
          <FormField
            label={t("instructions")}
            htmlFor="project-instructions"
            description={t("instructionsHint")}
          >
            <Textarea
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
              placeholder={t("instructionsPlaceholder")}
              rows={10}
              maxLength={20000}
              disabled={!editable}
            />
          </FormField>
          {editable && (
            <div className="flex justify-end">
              <Button
                disabled={!changed || !name.trim() || update.isPending}
                onClick={() =>
                  update.mutate({
                    name: name.trim(),
                    description: description.trim() || null,
                    instructions,
                    // Only when it was changed: a default agent this reader may
                    // not see reaches them as none, and saving the instructions
                    // must not clear it.
                    ...(agentId !== project.default_agent_id && { default_agent_id: agentId }),
                  })
                }
              >
                {t("save")}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {editable && (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6">
            <div>
              <p className="text-sm font-medium">{t("deleteProject")}</p>
              <p className="text-muted-foreground text-sm">{t("deleteProjectHint")}</p>
            </div>
            <Button variant="outline" onClick={() => setConfirmDelete(true)}>
              <Trash2 className="h-4 w-4" />
              {t("delete")}
            </Button>
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={t("deleteTitle", { name: project.name })}
        description={t("deleteProjectHint")}
        confirmLabel={t("delete")}
        confirmText={project.name}
        destructive
        loading={remove.isPending}
        onConfirm={async () => {
          await remove.mutateAsync();
          router.push(ROUTES.PROJECTS);
        }}
      />
    </div>
  );
}
