"use client";

import { useState } from "react";
import { toast } from "sonner";

import { AgentStatusBadge } from "@/components/agents/status-badge";
import {
  Badge,
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { useAgents } from "@/hooks";
import { submitFailure } from "@/lib/api-error";
import type { Agent } from "@/types/agents";
import type { Visibility } from "@/types/sharing";
import { useTranslations } from "next-intl";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";

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
  const tErrors = useTranslations("errors");
  const t = useTranslations("agents");
  const { create } = useAgents();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  // Organization by default. An agent is a thing a company builds, and one
  // nobody else can find is the exception - it used to be the rule, so every
  // agent was made invisible and then shared by hand.
  const [visibility, setVisibility] = useState<Visibility>("org");
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
        spec: {
          name,
          description: description || null,
          instructions: "",
          model_profile_id: null,
          model_settings: {},
          capabilities: [],
          collection_ids: [],
          skill_ids: [],
          context_ids: [],
          mcp_servers: [],
          budget: null,
        },
        visibility,
      });
      setName("");
      setDescription("");
      setVisibility("org");
      setErrors({});
      onOpenChange(false);
      onCreated(agent);
    } catch (error) {
      // The dialog stays open with everything still in it: the usual reason to
      // be here is a handle that is taken, which is one word away from working.
      const failure = submitFailure(
        error,
        {
          fields: ["name", "description"],
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
      <DialogContent className={DIALOG_CONFIRM}>
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
                {t.rich("handleDescription", {
                  handle: deriveHandle(name || t("handlePlaceholder")),
                  at: (chunks) => <span className="font-mono">@{chunks}</span>,
                })}
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
          <div className="space-y-1.5">
            <Label htmlFor="agent-visibility">{t("whoCanFindIt")}</Label>
            <Select
              value={visibility}
              onValueChange={(value) => setVisibility(value as Visibility)}
            >
              <SelectTrigger id="agent-visibility">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="org">{t("visibilityOrg")}</SelectItem>
                <SelectItem value="private">{t("visibilityPrivate")}</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">
              {t(visibility === "org" ? "visibilityOrgHint" : "visibilityPrivateHint")}
            </p>
          </div>

          {/* The row this is about to become, drawn from what has been typed.
              The handle and the description are what a colleague scanning the
              catalog reads, and they are easier to judge as a row than as three
              fields - a name that looked fine in an input is the one that
              truncates here. */}
          <div className="space-y-1.5">
            <Label>{t("preview")}</Label>
            <div className="border-border bg-card rounded-xl border p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-foreground truncate font-medium">
                    {name.trim() || t("supportCopilot")}
                  </p>
                  <p className="text-muted-foreground truncate font-mono text-xs">
                    @{deriveHandle(name || t("handlePlaceholder"))}
                  </p>
                </div>
                <AgentStatusBadge status="draft" />
              </div>
              <p className="text-muted-foreground mt-2 line-clamp-2 min-h-[2.5rem] text-sm">
                {description.trim() || t("answersCustomerQuestionsFrom")}
              </p>
              <Badge variant="outline" className="mt-1">
                {t(visibility === "org" ? "visibilityOrg" : "visibilityPrivate")}
              </Badge>
            </div>
          </div>
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
