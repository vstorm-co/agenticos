"use client";

import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  AudiencePicker,
  audiencePayload,
  type Audience,
} from "@/components/sharing/audience-picker";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Label,
  Textarea,
} from "@/components/ui";
import { useProjects } from "@/hooks/use-projects";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { Project } from "@/types/projects";
import { ProjectSandboxChoice } from "./project-sandbox-choice";
import { DefaultAgentSelect } from "./default-agent-select";
import { useProjectFolder } from "@/hooks/use-project-folder";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import type { LocalTarget } from "@/lib/desktop/commands";

/** Private to its creator until they share it: a project is somebody's work first. */
const ONLY_ME: Audience = { mode: "private", group_ids: [], user_ids: [] };

type Field = "name" | "description" | "instructions" | "default_agent_id" | "sandbox_connection_id";

/**
 * New project: a name, what it is for, the instructions every agent in it reads,
 * the agent a chat starts with, and who else may work in it.
 */
export function CreateProjectDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (project: Project) => void;
}) {
  const t = useTranslations("projects");
  const tErrors = useTranslations("errors");
  const { create } = useProjects();
  const shell = useShell();
  const folder = useProjectFolder(null);
  const [localFolder, setLocalFolder] = useState<LocalTarget | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  const [agentId, setAgentId] = useState<string | null>(null);
  const [sandbox, setSandbox] = useState("auto");
  const [audience, setAudience] = useState<Audience>(ONLY_ME);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  function clearError(field: Field) {
    if (errors[field]) setErrors(({ [field]: _removed, ...rest }) => rest);
  }

  const source = useId();
  function reset() {
    setLocalFolder(null);
    setName("");
    setDescription("");
    setInstructions("");
    setAgentId(null);
    setSandbox("auto");
    setAudience(ONLY_ME);
    setErrors({});
  }
  useUnsavedChanges(source, {
    dirty:
      open &&
      (name !== "" ||
        description !== "" ||
        instructions !== "" ||
        agentId !== null ||
        sandbox !== "auto" ||
        localFolder !== null ||
        audience.mode !== "private"),
    save:
      name.trim() !== "" && (sandbox !== "computer" || localFolder !== null)
        ? handleCreate
        : undefined,
    discard: () => {
      reset();
      onOpenChange(false);
    },
  });
  // This dialog has no trigger: only dismissal asks to change its open state.
  function close() {
    if (!create.isPending)
      useUnsavedChangesStore.getState().leave(() => onOpenChange(false), [source]);
  }

  async function handleCreate(): Promise<boolean> {
    if (create.isPending || name.trim() === "") return false;
    try {
      const project = await create.mutateAsync({
        name: name.trim(),
        description: description.trim() || null,
        instructions,
        default_agent_id: agentId,
        ...(sandbox === "auto" || sandbox === "computer"
          ? {}
          : sandbox === "state"
            ? { backend: "state" as const }
            : { backend: "service" as const, sandbox_connection_id: sandbox }),
        ...audiencePayload(audience),
      });
      if (localFolder) folder.bind(project.id, localFolder);
      reset();
      onCreated(project);
      return true;
    } catch (error) {
      const failure = submitFailure(
        error,
        {
          fields: [
            "name",
            "description",
            "instructions",
            "default_agent_id",
            "sandbox_connection_id",
          ] satisfies Field[],
          identifiedBy: "name",
        },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
      return false;
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent dismissible={!create.isPending} className={cn(DIALOG_COLUMN, DIALOG_FORM)}>
        <DialogHeader>
          <DialogTitle>{t("newProject")}</DialogTitle>
          <DialogDescription>{t("newProjectHint")}</DialogDescription>
        </DialogHeader>

        <div className="-mx-1.5 flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-1.5 py-1">
          <fieldset disabled={create.isPending} className="min-w-0 space-y-4">
            <legend className="sr-only">{t("newProject")}</legend>
            <FormField label={t("name")} htmlFor="new-project-name" error={errors.name}>
              <Input
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  clearError("name");
                }}
                placeholder={t("namePlaceholder")}
                maxLength={120}
              />
            </FormField>
            <FormField
              label={t("description")}
              htmlFor="new-project-description"
              error={errors.description}
            >
              <Input
                value={description}
                onChange={(event) => {
                  setDescription(event.target.value);
                  clearError("description");
                }}
                placeholder={t("descriptionPlaceholder")}
                maxLength={500}
              />
            </FormField>
            <FormField
              label={t("defaultAgent")}
              htmlFor="new-project-agent"
              description={t("defaultAgentHint")}
              error={errors.default_agent_id}
            >
              <DefaultAgentSelect
                id="new-project-agent"
                value={agentId}
                onChange={(next) => {
                  setAgentId(next);
                  clearError("default_agent_id");
                }}
              />
            </FormField>
            <FormField
              label={t("instructions")}
              htmlFor="new-project-instructions"
              description={t("instructionsHint")}
              error={errors.instructions}
            >
              <Textarea
                value={instructions}
                onChange={(event) => {
                  setInstructions(event.target.value);
                  clearError("instructions");
                }}
                placeholder={t("instructionsPlaceholder")}
                rows={5}
                maxLength={20000}
              />
            </FormField>
            <ProjectSandboxChoice
              value={sandbox}
              onChange={(next) => {
                setSandbox(next);
                clearError("sandbox_connection_id");
                if (next !== "computer") setLocalFolder(null);
              }}
              computer={
                isDesktopShell(shell) && folder.available
                  ? { target: localFolder, onChange: setLocalFolder, disabled: create.isPending }
                  : undefined
              }
              enabled={open}
              error={errors.sandbox_connection_id}
            />
            <div className="space-y-1.5">
              <Label>{t("whoWorksInIt")}</Label>
              <AudiencePicker value={audience} onChange={setAudience} />
            </div>
          </fieldset>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={close} disabled={create.isPending}>
            {t("cancel")}
          </Button>
          <Button
            onClick={handleCreate}
            loading={create.isPending}
            disabled={
              !name.trim() || create.isPending || (sandbox === "computer" && localFolder === null)
            }
          >
            {t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
