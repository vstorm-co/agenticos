"use client";

import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import type { NodeDefinition, StepChoice, WorkflowNodeRunRead } from "@/lib/workflows/types";

interface StepAttentionDialogProps {
  node: WorkflowNodeRunRead;
  /** The step's name as the run page calls it. */
  stepName: string;
  /** What the catalog says the step is; unknown for a step whose definition is gone. */
  definition: NodeDefinition | undefined;
  /** Whether the step's failure leaves by its error port. */
  routesErrors: boolean;
  /** Whether the step sits in a loop body, whose item-error policy then decides. */
  inLoop: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onResolve: (choice: StepChoice) => void;
  busy?: boolean;
}

/**
 * What a person decides for a step that needs attention: run it again, treat it as
 * failed (by its error route, or by failing the run), or - when the step reported after
 * its try was given up on - use that result.
 *
 * The first line says why the step is stuck in the words that matter to the choice: a
 * write that may already have happened is run again at the risk of doing it twice; a
 * step that stopped waiting has nothing left to wake it.
 */
export function StepAttentionDialog({
  node,
  stepName,
  definition,
  routesErrors,
  inLoop,
  open,
  onOpenChange,
  onResolve,
  busy,
}: StepAttentionDialogProps) {
  const t = useTranslations("pages.workflows");
  const reason =
    node.last_attempt_status === "uncertain" && definition?.effect_kind === "write"
      ? "stepResolveMayHaveHappened"
      : node.last_attempt_status === "completed"
        ? "stepResolveStoppedWaiting"
        : "stepResolveNeutral";
  const choose = (choice: StepChoice) => () => onResolve(choice);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{t("stepResolveTitle", { step: stepName })}</DialogTitle>
          <DialogDescription>{t(reason, { step: stepName })}</DialogDescription>
        </DialogHeader>
        {node.late_output !== null && <p className="text-sm">{t("stepResolveLate")}</p>}
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Button disabled={busy} onClick={choose("run_again")}>
              {t("stepRunAgain")}
            </Button>
            {node.late_output !== null && (
              <Button variant="outline" disabled={busy} onClick={choose("use_late_result")}>
                {t("stepUseLate")}
              </Button>
            )}
          </div>
          <div className="space-y-2">
            <p className="text-muted-foreground text-xs font-medium">{t("stepTreatAsFailed")}</p>
            <div className="flex flex-wrap gap-2">
              {(routesErrors || inLoop) && (
                <Button variant="outline" disabled={busy} onClick={choose("use_error_route")}>
                  {t("stepUseErrorRoute")}
                </Button>
              )}
              <Button variant="outline" disabled={busy} onClick={choose("fail_run")}>
                {t("stepFailRun")}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
