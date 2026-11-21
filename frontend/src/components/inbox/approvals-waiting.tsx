"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { PendingApproval } from "@/components/runs/approval-cards";
import { StepApprovalRow } from "@/components/runs/workflow-approvals-card";
import { useDecideApproval } from "@/hooks/use-runs";
import { useDecideWorkflowApproval } from "@/hooks/use-workflow-approvals";
import { ROUTES } from "@/lib/constants";
import type { WorkflowApprovalRead } from "@/lib/workflows/types";
import type { ToolApproval } from "@/types/runs";

import styles from "./inbox-row.module.css";

const SHOWN = 5;

export function ApprovalsWaiting({
  tools,
  steps,
}: {
  tools: ToolApproval[];
  steps: WorkflowApprovalRead[];
}) {
  const t = useTranslations("inbox.approvals");
  const router = useRouter();
  const decideTool = useDecideApproval();
  const decideStep = useDecideWorkflowApproval();
  const deciding = decideTool.isPending || decideStep.isPending;
  const queue = `${ROUTES.RUNS}?tab=approvals`;
  const shownSteps = steps.slice(0, SHOWN);

  return (
    <section aria-labelledby="inbox-approvals" className="border-b last:border-b-0">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4 pb-2 sm:px-5">
        <h2 id="inbox-approvals" className="text-muted-foreground text-xs font-medium">
          {t("title")}
        </h2>
        <Link
          href={queue}
          className="text-muted-foreground hover:text-foreground touch:min-h-11 inline-flex min-h-6 items-center gap-1 rounded-sm text-xs focus-visible:outline-2 focus-visible:outline-offset-4"
        >
          {t("open")}
          <ChevronRight className="size-3.5" aria-hidden />
        </Link>
      </div>
      <ul className="divide-y">
        {shownSteps.map((approval) => (
          <li key={approval.id}>
            <StepApprovalRow
              className={styles.approvalRow}
              approval={approval}
              deciding={deciding}
              onDecide={(approved, final, choice) =>
                decideStep.mutate({ id: approval.id, approved, final, choice })
              }
            />
          </li>
        ))}
        {tools.slice(0, SHOWN - shownSteps.length).map((approval) => (
          <PendingApproval
            className={styles.approvalRow}
            key={approval.id}
            approval={approval}
            deciding={deciding}
            onDecide={(approved) => decideTool.mutate({ id: approval.id, approved })}
            onOpenRun={() => router.push(`${queue}&run=${encodeURIComponent(approval.run_id)}`)}
          />
        ))}
      </ul>
    </section>
  );
}
