"use client";

import { Workflow as WorkflowIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useWorkflows } from "@/hooks";
import { WORKFLOW_CALL_TRIGGER } from "@/lib/workflows/triggers";

export interface WorkflowPickerProps {
  /** What the control is called: the field's own name, or the picker's when it has none. */
  label?: string;
  /** The chosen workflow's id, or null while none is. */
  value: string | null;
  onChange: (workflowId: string | null) => void;
  disabled?: boolean;
  error?: string;
}

/**
 * Which workflow a Run a workflow step runs: one published starting from
 * **Called by a workflow**, the only kind a step may call. A chosen workflow
 * that no longer is one - archived, or republished from another trigger - is
 * shown as such, because publishing would refuse it and a silent absence would
 * hide that.
 */
export function WorkflowPicker({ value, onChange, disabled, error, label }: WorkflowPickerProps) {
  const t = useTranslations("workflows");
  const caption = label ?? t("pickerWorkflowLabel");
  const { workflows, isLoading } = useWorkflows();
  const callable = workflows.filter(
    (workflow) => workflow.live_trigger === WORKFLOW_CALL_TRIGGER && workflow.status !== "archived",
  );
  const orphaned =
    value !== null && !isLoading && !callable.some((workflow) => workflow.id === value);

  return (
    <div className="space-y-2">
      <Label>{caption}</Label>
      <Select value={value ?? ""} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger aria-label={caption}>
          <SelectValue placeholder={t("pickerWorkflowPlaceholder")} />
        </SelectTrigger>
        <SelectContent>
          {callable.map((workflow) => (
            <SelectItem key={workflow.id} value={workflow.id}>
              <span className="flex items-center gap-2">
                <WorkflowIcon className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{workflow.name}</span>
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {callable.length === 0 && !isLoading && (
        <p className="text-muted-foreground text-xs">{t("pickerWorkflowNone")}</p>
      )}
      {orphaned && <p className="text-destructive text-xs">{t("pickerWorkflowGone")}</p>}
      {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}
