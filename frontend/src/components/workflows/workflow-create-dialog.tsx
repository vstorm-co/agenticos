"use client";

import { Workflow } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  MoreOptions,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui";
import { NodeTile } from "@/components/workflows/node-tile";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { WORKFLOW_TEMPLATES, type WorkflowTemplate } from "@/lib/workflows/templates";
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
  TRIGGER_CATEGORY,
  WEBHOOK_TRIGGER,
  WORKFLOW_CALL_TRIGGER,
  WORKFLOW_FAILED_TRIGGER,
} from "@/lib/workflows/triggers";
import type { WorkflowGraph } from "@/lib/workflows/types";

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

const COMMON_STARTS: ReadonlySet<string> = new Set([
  MANUAL_TRIGGER,
  API_TRIGGER,
  CHAT_TRIGGER,
  WEBHOOK_TRIGGER,
  SCHEDULE_TRIGGER,
  TABLE_RECORD_TRIGGER,
]);

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

/** What the reader chose: a blank draft (`graph` null) or a template's seed graph. */
export interface WorkflowCreateChoice {
  template_id?: "publicApi" | "markdownNotes";
  name: string;
  graph: WorkflowGraph | null;
}

/**
 * The "New workflow" dialog: how it starts - one trigger, on an otherwise empty
 * canvas - or one of the shipped templates.
 *
 * It holds no state and does no fetching — it hands the caller a
 * {@link WorkflowCreateChoice} and the page's `create` mutation does the rest,
 * routing into the editor on success. Templates are static (`WORKFLOW_TEMPLATES`);
 * their name and description are catalog copy keyed on the template id.
 */
export function WorkflowCreateDialog({
  open,
  onOpenChange,
  onChoose,
  busy,
  canProvisionTables = true,
}: {
  canProvisionTables?: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChoose: (choice: WorkflowCreateChoice) => void;
  busy: boolean;
}) {
  const t = useTranslations("pages.workflows");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_COLUMN, DIALOG_FORM)}>
        <DialogHeader>
          <DialogTitle>{t("createDialogTitle")}</DialogTitle>
          <DialogDescription>{t("createDialogDescription")}</DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="start" className="flex min-h-0 flex-1 flex-col gap-4">
          <TabsList>
            <TabsTrigger value="start">{t("startHeading")}</TabsTrigger>
            <TabsTrigger value="templates">{t("templatesHeading")}</TabsTrigger>
          </TabsList>
          <div className={DIALOG_BODY}>
            <TabsContent value="start" className="mt-0 space-y-4">
              <StartList
                starts={STARTS.filter((start) => COMMON_STARTS.has(start.id))}
                busy={busy}
                onChoose={onChoose}
              />

              <MoreOptions label={t("moreStarts")}>
                <StartList
                  starts={STARTS.filter((start) => !COMMON_STARTS.has(start.id))}
                  busy={busy}
                  onChoose={onChoose}
                />
              </MoreOptions>
            </TabsContent>
            <TabsContent value="templates" className="mt-0 space-y-3">
              <p className="text-muted-foreground pt-2 text-xs font-medium tracking-wide uppercase">
                {t("templatesHeading")}
              </p>

              <TemplateList templates={WORKFLOW_TEMPLATES} busy={busy} onChoose={onChoose} />

              <p className="text-muted-foreground pt-2 text-xs font-medium tracking-wide uppercase">
                {t("automationsHeading")}
              </p>
              {(["publicApi", "markdownNotes"] as const).map((id) => (
                <button
                  key={id}
                  type="button"
                  disabled={busy || !canProvisionTables}
                  title={!canProvisionTables ? t("templatesNeedTables") : undefined}
                  className="hover:bg-accent/50 flex w-full items-start gap-3 rounded-xl border p-4 text-left transition-colors"
                  onClick={() =>
                    onChoose({ name: t(`templates.${id}.name`), graph: null, template_id: id })
                  }
                >
                  <Workflow className="text-muted-foreground mt-0.5 size-5 shrink-0" />
                  <span>
                    <span className="block text-sm font-semibold">{t(`templates.${id}.name`)}</span>
                    <span className="text-muted-foreground mt-1 block text-sm">
                      {t(`templates.${id}.description`)}
                    </span>
                  </span>
                </button>
              ))}
            </TabsContent>
          </div>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

/** One group of templates, each with its copy and a Use button. */
function TemplateList({
  templates,
  busy,
  onChoose,
}: {
  templates: readonly WorkflowTemplate[];
  busy: boolean;
  onChoose: (choice: WorkflowCreateChoice) => void;
}) {
  const t = useTranslations("pages.workflows");
  return (
    <>
      {templates.map((template) => (
        <div
          key={template.id}
          className="flex items-start justify-between gap-4 rounded-lg border p-4"
        >
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-2">
              <Workflow className="text-muted-foreground size-4 shrink-0" />
              <span className="font-medium">{t(`templates.${template.id}.name`)}</span>
            </div>
            <p className="text-muted-foreground text-sm">
              {t(`templates.${template.id}.description`)}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="shrink-0"
            disabled={busy}
            onClick={() =>
              onChoose({ name: t(`templates.${template.id}.name`), graph: template.graph })
            }
          >
            {t("useTemplate")}
          </Button>
        </div>
      ))}
    </>
  );
}

function StartList({
  starts,
  busy,
  onChoose,
}: {
  starts: readonly (typeof STARTS)[number][];
  busy: boolean;
  onChoose: (choice: WorkflowCreateChoice) => void;
}) {
  const t = useTranslations("pages.workflows");
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {starts.map((start) => {
        return (
          <button
            key={start.id}
            type="button"
            disabled={busy}
            onClick={() =>
              onChoose({ name: t("untitledWorkflow"), graph: startingGraph(start.id) })
            }
            className="hover:border-foreground/30 hover:bg-accent flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors disabled:opacity-50"
          >
            <NodeTile
              definitionId={start.id}
              category={TRIGGER_CATEGORY}
              className="size-8 rounded-lg"
              iconClassName="size-4"
            />
            <span className="min-w-0 space-y-0.5">
              <span className="block text-sm font-medium">{t(`start.${start.key}.name`)}</span>
              <span className="text-muted-foreground block text-xs">
                {t(`start.${start.key}.description`)}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
