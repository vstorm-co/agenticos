"use client";

import { useState } from "react";
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
import { DefaultAgentSelect } from "./default-agent-select";

/** Private to its creator until they share it: a project is somebody's work first. */
const ONLY_ME: Audience = { mode: "private", group_ids: [], user_ids: [] };

type Field = "name" | "description" | "instructions" | "default_agent_id";

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
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  const [agentId, setAgentId] = useState<string | null>(null);
  const [audience, setAudience] = useState<Audience>(ONLY_ME);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  async function handleCreate() {
    try {
      const project = await create.mutateAsync({
        name: name.trim(),
        description: description.trim() || null,
        instructions,
        default_agent_id: agentId,
        ...audiencePayload(audience),
      });
      setName("");
      setDescription("");
      setInstructions("");
      setAgentId(null);
      setAudience(ONLY_ME);
      setErrors({});
      onCreated(project);
    } catch (error) {
      const failure = submitFailure(
        error,
        {
          fields: ["name", "description", "instructions", "default_agent_id"] satisfies Field[],
          identifiedBy: "name",
        },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_COLUMN, DIALOG_FORM)}>
        <DialogHeader>
          <DialogTitle>{t("newProject")}</DialogTitle>
          <DialogDescription>{t("newProjectHint")}</DialogDescription>
        </DialogHeader>

        <div className="-mx-1.5 flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-1.5 py-1">
          <FormField label={t("name")} htmlFor="new-project-name" error={errors.name}>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
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
              onChange={(event) => setDescription(event.target.value)}
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
            <DefaultAgentSelect id="new-project-agent" value={agentId} onChange={setAgentId} />
          </FormField>
          <FormField
            label={t("instructions")}
            htmlFor="new-project-instructions"
            description={t("instructionsHint")}
            error={errors.instructions}
          >
            <Textarea
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
              placeholder={t("instructionsPlaceholder")}
              rows={5}
              maxLength={20000}
            />
          </FormField>
          <div className="space-y-1.5">
            <Label>{t("whoWorksInIt")}</Label>
            <AudiencePicker value={audience} onChange={setAudience} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button onClick={handleCreate} disabled={!name.trim() || create.isPending}>
            {t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
