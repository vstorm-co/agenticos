"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { useRouter } from "@/lib/locale-navigation";
import {
  Button,
  Card,
  CardContent,
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
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { ROUTES } from "@/lib/constants";
import type { Project } from "@/types/projects";
import { ContextHelp } from "@/components/ui/context-help";
import { ProjectSandboxSummary } from "./project-sandbox-choice";
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
  const editable =
    project.can_edit && !["queued", "running"].includes(project.workspace_move?.status ?? "");
  const changed =
    name !== project.name ||
    description !== (project.description ?? "") ||
    instructions !== project.instructions ||
    agentId !== project.default_agent_id;

  const discard = () => {
    setName(project.name);
    setDescription(project.description ?? "");
    setInstructions(project.instructions);
    setAgentId(project.default_agent_id);
  };
  const save = async (): Promise<boolean> => {
    try {
      await update.mutateAsync({
        name: name.trim(),
        description: description.trim() || null,
        instructions,
        // Saving instructions must not clear an unchanged, invisible default agent.
        ...(agentId !== project.default_agent_id && { default_agent_id: agentId }),
      });
      return true;
    } catch {
      // The mutation reports the failure; keep the editor and its draft in place.
      return false;
    }
  };
  useUnsavedChanges(`project-settings:${project.id}`, {
    dirty: editable && changed,
    save: name.trim() ? save : undefined,
    discard,
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="p-4 sm:p-5">
          <MarkdownEditor
            id="project-instructions"
            label={t("instructions")}
            toolbar={
              <>
                <div className="flex min-w-0 flex-1 items-center gap-1">
                  <CardTitle className="min-w-0 truncate text-sm">{t("instructions")}</CardTitle>
                  <ContextHelp>{t("instructionsHint")}</ContextHelp>
                </div>
                <MarkdownModeToggle mode={mode} onChange={setMode} />
              </>
            }
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

      <ProjectSandboxSummary project={project} />
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
          {/* One save for both cards: they are one record, written in one request. */}
          {editable && (
            <div className="flex justify-end">
              <Button
                loading={update.isPending}
                disabled={!changed || !name.trim()}
                onClick={() => void save()}
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
