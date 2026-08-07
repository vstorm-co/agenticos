"use client";

import { useState } from "react";
import { Button } from "@/components/ui";
import { usePermissions } from "@/hooks";
import type { ActionRequest, ReviewConfig, Decision } from "@/types";
import { Perm } from "@/types/permissions";
import { Wrench, AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

interface ToolApprovalDialogProps {
  actionRequests: ActionRequest[];
  reviewConfigs: ReviewConfig[];
  onDecisions: (decisions: Decision[]) => void;
  disabled?: boolean;
}

/**
 * The decision a parked run is waiting on, taken where the conversation is.
 *
 * **It checks `approvals:decide` itself**, for the same reason the model picker
 * beside it checks `connections:manage`: the permission belongs to the write, and
 * `onDecisions` sends `POST /approvals/{id}` followed by `POST /runs/{id}/resume`,
 * both gated on `Perm.APPROVALS_DECIDE`. Running an agent is not - `member` and
 * `builder` hold `agents:run` and not the decision - so the everyday chat user was
 * offered editable arguments and a Submit, and refused by the API on the first
 * call. `/runs` had this right from the start (`canDecide`); its copy of the
 * control in chat never asked.
 *
 * What stays is what is not a write: the banner and each parked call's arguments,
 * which arrived over this caller's own socket and are how they know what the run
 * is waiting for. Only the controls go, replaced by the sentence that says who can
 * decide - a panel that goes quiet leaves a stopped conversation unexplained.
 */
export function ToolApprovalDialog({
  actionRequests,
  onDecisions,
  disabled = false,
}: ToolApprovalDialogProps) {
  const t = useTranslations("chat");
  const { can } = usePermissions();
  const mayDecide = can(Perm.approvalsDecide);
  const [editedArgs, setEditedArgs] = useState<Record<string, string>>(() =>
    Object.fromEntries(actionRequests.map((a) => [a.id, JSON.stringify(a.args, null, 2)])),
  );
  const [hasChanges, setHasChanges] = useState(false);

  const handleArgsChange = (id: string, text: string) => {
    setEditedArgs((prev) => ({ ...prev, [id]: text }));
    setHasChanges(true);
  };

  const handleCancel = () => {
    setEditedArgs(
      Object.fromEntries(actionRequests.map((a) => [a.id, JSON.stringify(a.args, null, 2)])),
    );
    setHasChanges(false);
  };

  const handleSave = () => {
    for (const id of Object.keys(editedArgs)) {
      try {
        JSON.parse(editedArgs[id] ?? "");
      } catch {
        return; // Invalid JSON, don't save
      }
    }
    setHasChanges(false);
  };

  const handleSubmit = () => {
    const decisions: Decision[] = actionRequests.map((a) => {
      try {
        const parsed = JSON.parse(editedArgs[a.id] ?? "");
        const original = JSON.stringify(a.args);
        const edited = JSON.stringify(parsed);

        if (original !== edited) {
          return {
            type: "edit" as const,
            editedAction: { id: a.id, tool_name: a.tool_name, args: parsed },
          };
        }
        return { type: "approve" as const };
      } catch {
        return { type: "reject" as const };
      }
    });
    onDecisions(decisions);
  };

  return (
    <div className="border-warning/50 bg-warning/[0.06] space-y-3 rounded-lg border p-3">
      <div className="text-warning flex items-center gap-2 text-sm">
        <AlertTriangle className="h-4 w-4" />
        <span className="font-medium">{t("toolApprovalRequired")}</span>
      </div>

      {actionRequests.map((action) => (
        <div key={action.id} className="space-y-1.5">
          <div className="flex items-center gap-2">
            <Wrench className="text-muted-foreground h-3.5 w-3.5" />
            <code className="text-xs font-semibold">{action.tool_name}</code>
          </div>
          <textarea
            className={cn(
              "bg-background w-full resize-none rounded border p-2 font-mono text-xs",
              "max-h-[200px] min-h-[80px]",
            )}
            value={editedArgs[action.id]}
            onChange={(e) => handleArgsChange(action.id, e.target.value)}
            // Editing the arguments is part of the decision, so it goes with the
            // buttons; reading them is not, which is why the field stays.
            disabled={disabled || !mayDecide}
            rows={Math.min(10, (editedArgs[action.id]?.split("\n").length || 3) + 1)}
          />
        </div>
      ))}

      {mayDecide ? (
        <div className="flex justify-end gap-2 border-t pt-1">
          {hasChanges && (
            <>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs"
                onClick={handleCancel}
                disabled={disabled}
              >
                {t("cancel")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs"
                onClick={handleSave}
                disabled={disabled}
              >
                {t("save")}
              </Button>
            </>
          )}
          <Button size="sm" className="h-7 text-xs" onClick={handleSubmit} disabled={disabled}>
            {t("submitDecisions", { count: actionRequests.length })}
          </Button>
        </div>
      ) : (
        <p className="text-muted-foreground border-t pt-2 text-xs">
          {t("decidingNeedsPermission")}
        </p>
      )}
    </div>
  );
}
