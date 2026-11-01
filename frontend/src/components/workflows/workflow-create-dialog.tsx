"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  AudiencePicker,
  EVERYONE,
  audiencePayload,
  type Audience,
} from "@/components/sharing/audience-picker";
import { ChipsInput } from "@/components/agents/chips-input";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  MoreOptions,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { WorkflowCreate, WorkflowGraph } from "@/lib/workflows/types";
import {
  API_TRIGGER,
  CHANNEL_MESSAGE_TRIGGER,
  CHAT_TRIGGER,
  FORM_TRIGGER,
  GITHUB_TRIGGER,
  GMAIL_TRIGGER,
  OUTLOOK_TRIGGER,
  MANUAL_TRIGGER,
  SCHEDULE_TRIGGER,
  TABLE_RECORD_TRIGGER,
  WEBHOOK_TRIGGER,
  WORKFLOW_CALL_TRIGGER,
  WORKFLOW_FAILED_TRIGGER,
} from "@/lib/workflows/triggers";

/** The ways a new workflow can start, in the order a builder reaches for them. */
const STARTS = [
  { id: MANUAL_TRIGGER, key: "manual" },
  { id: API_TRIGGER, key: "api" },
  { id: CHAT_TRIGGER, key: "chat" },
  { id: WEBHOOK_TRIGGER, key: "webhook" },
  { id: GITHUB_TRIGGER, key: "github" },
  { id: GMAIL_TRIGGER, key: "gmail" },
  { id: OUTLOOK_TRIGGER, key: "outlook" },
  { id: SCHEDULE_TRIGGER, key: "schedule" },
  { id: TABLE_RECORD_TRIGGER, key: "tableRecord" },
  { id: FORM_TRIGGER, key: "form" },
  { id: CHANNEL_MESSAGE_TRIGGER, key: "channelMessage" },
  { id: WORKFLOW_CALL_TRIGGER, key: "workflowCall" },
  { id: WORKFLOW_FAILED_TRIGGER, key: "workflowFailed" },
] as const;

/** A draft of one trigger node - where every new workflow begins. */
export function startingGraph(definitionId: string): WorkflowGraph {
  const id = crypto.randomUUID();
  return {
    entry_node_id: id,
    nodes: [
      {
        id,
        definition_id: definitionId,
        definition_version: 1,
        config: {},
        layout: { x: 0, y: 0 },
      },
    ],
    edges: [],
    bindings: [],
    scopes: [],
  };
}

export interface WorkflowCreateChoice extends WorkflowCreate {
  graph: WorkflowGraph | null;
}

/** Name and audience first, using the same creation controls as the agent builder. */
export function WorkflowCreateDialog({
  open,
  onOpenChange,
  onChoose,
  busy,
  initial,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChoose: (choice: WorkflowCreateChoice) => void;
  busy: boolean;
  initial?: WorkflowCreateChoice;
}) {
  const t = useTranslations("pages.workflows");
  const common = useTranslations("common");
  const agent = useTranslations("agents");
  const audienceText = useTranslations("audience");
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [tags, setTags] = useState<string[]>([]);
  const [audience, setAudience] = useState<Audience>(
    initial?.template_id ? { ...EVERYONE, mode: "private" } : EVERYONE,
  );
  const [start, setStart] = useState<string>(MANUAL_TRIGGER);
  const chosen = STARTS.find((entry) => entry.id === start)!;
  const emptyAudience =
    audience.mode === "chosen" && !audience.group_ids.length && !audience.user_ids.length;
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!busy) onOpenChange(next);
      }}
    >
      <DialogContent className={cn(DIALOG_COLUMN, DIALOG_FORM)}>
        <DialogHeader>
          <DialogTitle>{t("createDialogTitle")}</DialogTitle>
          <DialogDescription>{agent("startsAsDraftNothing")}</DialogDescription>
        </DialogHeader>
        <form
          className="flex min-h-0 flex-1 flex-col gap-6"
          onSubmit={(event) => {
            event.preventDefault();
            if (!name.trim() || busy || emptyAudience) return;
            onChoose({
              ...initial,
              name: name.trim(),
              description: description.trim() || null,
              tags,
              ...audiencePayload(audience),
              graph: initial?.graph ?? (initial?.template_id ? null : startingGraph(start)),
            });
          }}
        >
          <div className={cn(DIALOG_BODY, "space-y-6")}>
            <div className="space-y-2">
              <Label htmlFor="workflow-create-name">{t("createName")}</Label>
              <Input
                id="workflow-create-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={128}
                placeholder={t("createNamePlaceholder")}
                disabled={busy}
                required
              />
            </div>
            <div className="space-y-2">
              <Label>{audienceText("label")}</Label>
              <AudiencePicker value={audience} onChange={setAudience} disabled={busy} />
            </div>
            {!initial && (
              <div className="space-y-2">
                <Label htmlFor="workflow-create-start">{t("startHeading")}</Label>
                <Select value={start} onValueChange={setStart} disabled={busy}>
                  <SelectTrigger id="workflow-create-start">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {STARTS.map((entry) => (
                      <SelectItem key={entry.id} value={entry.id}>
                        {t(`start.${entry.key}.name`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-muted-foreground text-xs">
                  {t(`start.${chosen.key}.description`)}
                </p>
              </div>
            )}
            {initial && (
              <div className="bg-muted/30 rounded-lg border p-3 text-sm">
                <p className="font-medium">{t("selectedTemplate", { name: initial.name })}</p>
                <p className="text-muted-foreground mt-1">{initial.description}</p>
              </div>
            )}
            <MoreOptions label={agent("moreOptions")}>
              <div className="space-y-2">
                <Label htmlFor="workflow-create-description">{t("createDescription")}</Label>
                <Textarea
                  id="workflow-create-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  maxLength={2000}
                  rows={3}
                  disabled={busy}
                />
              </div>
              <div className="space-y-2">
                <Label>{t("createTags")}</Label>
                <ChipsInput
                  values={tags}
                  onChange={setTags}
                  inputLabel={t("createTags")}
                  removeLabel={(tag) => t("removeTag", { tag })}
                  maxItems={10}
                  maxLength={32}
                  disabled={busy}
                />
              </div>
            </MoreOptions>
          </div>
          <DialogFooter className="border-t pt-4">
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => onOpenChange(false)}
            >
              {common("cancel")}
            </Button>
            <Button type="submit" disabled={!name.trim() || busy || emptyAudience}>
              {common("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
