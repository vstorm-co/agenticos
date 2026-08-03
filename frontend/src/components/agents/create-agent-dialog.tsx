"use client";

import { useState } from "react";
import { toast } from "sonner";

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
  Textarea,
} from "@/components/ui";
import { useAgents } from "@/hooks";
import { submitFailure } from "@/lib/api-error";
import type { Agent } from "@/types/agents";
import { useTranslations } from "next-intl";

/** What the backend will accept, so a longer name is refused before it is sent. */
const MAX_NAME = 128;
const MAX_DESCRIPTION = 1000;

/**
 * The handle an agent will be addressed by, derived from its name.
 *
 * A mirror of `slugify` in `backend/app/services/agent_registry.py`, fallback
 * included: a name with nothing slug-able in it really does become `agent`
 * there. Mirroring it exactly is the point - this is shown as a prediction, and
 * a prediction that quietly disagrees with the server is worse than none. The
 * server remains the authority; it derives the handle again on create and its
 * answer is the one that is stored.
 */
export function deriveHandle(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug.slice(0, 64) || "agent";
}

interface CreateAgentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (agent: Agent) => void;
}

/**
 * New agent: a name, a description, and the handle the name will produce.
 *
 * The handle is on screen while the name is being typed because it is the part
 * that cannot be changed afterwards and the part a duplicate is refused on. A
 * reader who has seen `@support` under the field can act on "that handle is
 * taken"; one who has not is being told about a value they never entered.
 */
export function CreateAgentDialog({ open, onOpenChange, onCreated }: CreateAgentDialogProps) {
  const t = useTranslations("agents");
  const { create } = useAgents();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  function edit(field: "name" | "description", value: string) {
    if (field === "name") setName(value);
    else setDescription(value);
    // The server's verdict was about the value that was sent. Keeping it on
    // screen while the reader changes that value is how a form ends up marking
    // a name that is now perfectly good.
    if (errors[field]) setErrors(({ [field]: _removed, ...rest }) => rest);
  }

  async function handleCreate() {
    try {
      const agent = await create.mutateAsync({
        name,
        description: description || null,
        instructions: "",
        model_profile_id: null,
        model_settings: {},
        capabilities: [],
        collection_ids: [],
        skill_ids: [],
        mcp_server_ids: [],
        budget: null,
      });
      setName("");
      setDescription("");
      setErrors({});
      onOpenChange(false);
      onCreated(agent);
    } catch (error) {
      // The dialog stays open with everything still in it: the usual reason to
      // be here is a handle that is taken, which is one word away from working.
      const failure = submitFailure(error, {
        fields: ["name", "description"],
        identifiedBy: "name",
      });
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("newAgent")}</DialogTitle>
          <DialogDescription>{t("startsAsDraftNothing")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <FormField
            label={t("name4")}
            htmlFor="agent-name"
            error={errors.name}
            description={
              <>
                It will be mentioned as{" "}
                <span className="font-mono">@{deriveHandle(name || "your agent")}</span>
                {t("whichFixedOnceCreated")}
              </>
            }
          >
            <Input
              value={name}
              onChange={(event) => edit("name", event.target.value)}
              placeholder={t("supportCopilot")}
              maxLength={MAX_NAME}
            />
          </FormField>
          <FormField
            label={t("description")}
            htmlFor="agent-description"
            error={errors.description}
          >
            <Textarea
              value={description}
              onChange={(event) => edit("description", event.target.value)}
              placeholder={t("answersCustomerQuestionsFrom")}
              maxLength={MAX_DESCRIPTION}
              rows={2}
            />
          </FormField>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel2")}
          </Button>
          <Button onClick={handleCreate} disabled={!name.trim() || create.isPending}>
            {t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
