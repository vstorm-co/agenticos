"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { useRouter } from "@/lib/locale-navigation";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ConfirmDialog,
  FormField,
  Input,
  MarkdownEditor,
  MarkdownModeToggle,
  type MarkdownMode,
} from "@/components/ui";
import { useProject } from "@/hooks/use-projects";
import { ROUTES } from "@/lib/constants";
import type { Project } from "@/types/projects";
import { DefaultAgentSelect } from "./default-agent-select";

/**
 * What every agent in the project is told, and what the project is.
 *
 * The instructions first and in the Agent Builder's own card - Markdown, with
 * Source and Preview in its header - since they are the same kind of text and
 * the tab is named for them. Read-only to whoever may not change them: they are
 * worth reading for anybody working in the project, since they shape every
 * answer in it.
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
  const [mode, setMode] = useState<MarkdownMode>(project.can_edit ? "source" : "preview");
  const editable = project.can_edit;
  const changed =
    name !== project.name ||
    description !== (project.description ?? "") ||
    instructions !== project.instructions ||
    agentId !== project.default_agent_id;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex-row items-start gap-3 space-y-0">
          <div className="min-w-0 flex-1 space-y-1.5">
            <CardTitle>{t("instructions")}</CardTitle>
            <CardDescription>{t("instructionsHint")}</CardDescription>
          </div>
          <MarkdownModeToggle mode={mode} onChange={setMode} />
        </CardHeader>
        <CardContent>
          <MarkdownEditor
            id="project-instructions"
            label={t("instructions")}
            value={instructions}
            onChange={(next) => setInstructions(next)}
            placeholder={t("instructionsPlaceholder")}
            rows={14}
            maxLength={20000}
            disabled={!editable}
            mode={mode}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("details")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
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
        </CardContent>
      </Card>

      {/* One save for both cards: they are one record, written in one request. */}
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
