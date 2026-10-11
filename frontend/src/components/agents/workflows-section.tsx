"use client";

import Link from "next/link";
import { AlertTriangle, Plus, Workflow as WorkflowIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { CapabilityDetail } from "@/components/agents/capability-settings";
import { SchemaForm } from "@/components/agents/schema-form";
import { Badge, Checkbox, Label, Skeleton } from "@/components/ui";
import { usePermissions, useWorkflows } from "@/hooks";
import { capabilityConfigErrors } from "@/lib/agent-spec";
import type { FieldProblem } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { BY_HAND_TRIGGERS, WORKFLOW_CALL_TRIGGER } from "@/lib/workflows/triggers";
import type { WorkflowRead } from "@/lib/workflows/types";
import { Perm } from "@/types/permissions";
import type { CapabilityBindingSpec, CapabilityCatalogEntry, JsonSchema } from "@/types/agents";

/** The workflow ids stored on the binding, keeping only what reads as one. */
export function workflowIdsOf(config: Record<string, unknown>): string[] {
  const raw = config.workflow_ids;
  return Array.isArray(raw) ? raw.filter((id): id is string => typeof id === "string") : [];
}

/**
 * Whether an agent may start this workflow: published, live, and starting by
 * hand, by the API or by a call - the doors `run_workflow` goes through.
 */
export function agentStartable(workflow: WorkflowRead): boolean {
  if (workflow.status === "archived" || workflow.current_version_id === null) return false;
  const trigger = workflow.live_trigger;
  return trigger === null || BY_HAND_TRIGGERS.has(trigger) || trigger === WORKFLOW_CALL_TRIGGER;
}

interface WorkflowsSectionProps {
  definition: CapabilityCatalogEntry | undefined;
  binding: CapabilityBindingSpec;
  onChange: (binding: CapabilityBindingSpec) => void;
  onToggleEnabled?: () => void;
  readOnly?: boolean;
  disabled?: boolean;
  configProblems?: readonly FieldProblem[];
}

/**
 * Which workflows the agent may start, as tools.
 *
 * One row per workflow, ticked on or off: a generated form would draw a list of
 * ids. A workflow the agent could not start - a draft, an archived one, one that
 * starts from a webhook or a schedule - is shown but cannot be ticked, saying
 * why, so the list reads as the registry does rather than as a mystery subset.
 */
export function WorkflowsSection({
  definition,
  binding,
  onChange,
  onToggleEnabled,
  readOnly,
  disabled,
  configProblems,
}: WorkflowsSectionProps) {
  const t = useTranslations("agents");
  const { can } = usePermissions();
  const mayView = can(Perm.workflowsView);
  const { workflows, isLoading } = useWorkflows({ enabled: mayView });
  const configErrors = capabilityConfigErrors(configProblems ?? [], binding.id);

  if (!definition) return null;

  const chosen = workflowIdsOf(binding.config);
  const known = new Set(workflows.map((workflow) => workflow.id));
  // Kept on screen, the tables panel's rule: an id that quietly vanished from the
  // form is still in the spec, and publish is where it would surface.
  const orphaned = chosen.filter((id) => mayView && !isLoading && !known.has(id));
  const live = workflows.filter((workflow) => workflow.status !== "archived");

  const write = (next: string[]) =>
    onChange({ ...binding, config: { ...binding.config, workflow_ids: next } });
  const toggle = (id: string) =>
    write(chosen.includes(id) ? chosen.filter((one) => one !== id) : [...chosen, id]);

  const controls = (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label>{t("workflowsGrantsLabel")}</Label>
        <p className="text-muted-foreground text-xs">{t("workflowsGrantsDetail")}</p>
      </div>

      {!mayView ? (
        <p className="text-muted-foreground text-sm">{t("workflowsNeedsPermission")}</p>
      ) : isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : live.length === 0 ? (
        <div className="border-border text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
          {t("workflowsNone")}
        </div>
      ) : (
        <ul className="divide-border border-border divide-y rounded-lg border">
          {live.map((workflow) => {
            const startable = agentStartable(workflow);
            const on = chosen.includes(workflow.id);
            return (
              <li key={workflow.id} className="p-3">
                <label className="flex min-w-0 cursor-pointer items-start gap-3">
                  <Checkbox
                    checked={on}
                    onCheckedChange={() => toggle(workflow.id)}
                    // One already chosen stays untickable off, so a spec can be mended.
                    disabled={disabled || (!startable && !on)}
                    aria-label={t("workflowsGrantToggle", { name: workflow.name })}
                    className="mt-0.5"
                  />
                  <span className="min-w-0">
                    <span className="text-foreground flex items-center gap-2 text-sm font-medium">
                      <WorkflowIcon
                        className="text-muted-foreground h-3.5 w-3.5 shrink-0"
                        aria-hidden
                      />
                      <span className="truncate">{workflow.name}</span>
                    </span>
                    {startable ? (
                      workflow.description && (
                        <span className="text-muted-foreground block truncate text-xs">
                          {workflow.description}
                        </span>
                      )
                    ) : (
                      <span className="text-muted-foreground block text-xs">
                        {t(
                          workflow.current_version_id === null
                            ? "workflowsNotPublished"
                            : "workflowsStartsElsewhere",
                        )}
                      </span>
                    )}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}

      {orphaned.map((id) => (
        <p key={id} className="text-foreground/70 flex items-center gap-1.5 text-xs" role="status">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("workflowsOrphaned")}
          <Badge variant="outline" className="font-mono">
            {id}
          </Badge>
        </p>
      ))}

      <Link
        href={ROUTES.WORKFLOWS}
        className="text-muted-foreground inline-flex items-center gap-1.5 text-xs underline underline-offset-4"
      >
        <Plus className="h-3.5 w-3.5" aria-hidden />
        {t("workflowsManage")}
      </Link>

      {definition.config_schema && (
        <SchemaForm
          idPrefix={binding.id}
          schema={withoutWorkflows(definition.config_schema)}
          value={binding.config}
          disabled={disabled}
          errors={configErrors}
          onChange={(config) =>
            onChange({ ...binding, config: { ...config, workflow_ids: chosen } })
          }
        />
      )}
    </div>
  );

  return (
    <CapabilityDetail
      binding={binding}
      definition={definition}
      onChange={onChange}
      onToggleEnabled={onToggleEnabled}
      readOnly={readOnly}
      disabled={disabled}
      configProblems={configProblems}
      settingsExtra={controls}
      hideConfigForm
    />
  );
}

/** The schema with the workflow ids taken out: this panel draws them itself. */
function withoutWorkflows(schema: JsonSchema): JsonSchema {
  const properties = Object.fromEntries(
    Object.entries(schema.properties ?? {}).filter(([name]) => name !== "workflow_ids"),
  );
  return { ...schema, properties };
}
