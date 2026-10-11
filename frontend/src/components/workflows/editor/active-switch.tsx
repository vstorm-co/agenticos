"use client";

import { useTranslations } from "next-intl";

import { Label, Switch } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { WorkflowDetail } from "@/lib/workflows/types";

/**
 * Whether a published workflow's unattended trigger - a webhook, a schedule,
 * a new table record - is on, and the switch that pauses or resumes it.
 *
 * Shown only for a live version with such a trigger: a workflow started by hand,
 * by an API call or from chat has nothing that runs without someone there, so
 * there is nothing to switch. Someone who may not change the workflow sees the
 * state without the switch.
 */
export function ActiveSwitch({
  workflow,
  canEdit,
  pending,
  onChange,
}: {
  workflow: WorkflowDetail;
  canEdit: boolean;
  pending: boolean;
  onChange: (active: boolean) => void;
}) {
  const t = useTranslations("pages.workflows");
  if (workflow.current_version_id === null || workflow.trigger_active === null) return null;
  const active = workflow.trigger_active;

  if (!canEdit) {
    return (
      <span className="text-muted-foreground inline-flex items-center gap-1.5 text-sm">
        <span
          aria-hidden="true"
          className={cn(
            "size-2 rounded-full",
            active ? "bg-emerald-500" : "bg-muted-foreground/40",
          )}
        />
        {active ? t("activeOn") : t("activeOff")}
      </span>
    );
  }
  return (
    <div
      className="flex items-center gap-2"
      title={active ? t("activeHintOn") : t("activeHintOff")}
    >
      <Switch id="workflow-active" checked={active} disabled={pending} onCheckedChange={onChange} />
      <Label htmlFor="workflow-active" className="text-sm font-normal">
        {active ? t("activeOn") : t("activeOff")}
      </Label>
    </div>
  );
}
