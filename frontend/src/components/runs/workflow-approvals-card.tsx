"use client";

import { useDeferredValue, useId, useState } from "react";
import Link from "next/link";
import { CheckCircle2, GitCompare, Undo2, UserCheck, XCircle } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { Badge, Button, LineDiff, ListCard, MarkdownEditor, Textarea } from "@/components/ui";
import { useWorkflowApprovals } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { cn, formatDate } from "@/lib/utils";
import { MAX_PROPOSAL_CHARS, type WorkflowApprovalRead } from "@/lib/workflows/types";
import { useAuthStore } from "@/stores/auth-store";

/**
 * The workflow steps waiting on a person: what each asks, from which workflow,
 * and the two buttons that answer it.
 *
 * Beside the tool approvals rather than inside their table: a step asks a
 * question in its own words and has no tool or arguments, and deciding it
 * wakes a workflow run, not an agent. Nothing is drawn while nothing waits, so
 * the tab keeps opening on the tool queue it always did.
 */
export function WorkflowApprovalsCard() {
  const t = useTranslations("pages.runs");
  const { approvals, total, decide } = useWorkflowApprovals();

  if (total === 0) return null;

  return (
    <ListCard
      title={t("stepApprovalsTitle")}
      counted={t("stepApprovalsCounted", { count: total })}
      contentClassName="divide-y p-0"
    >
      {approvals.map((approval) => (
        <StepApprovalRow
          key={approval.id}
          approval={approval}
          deciding={decide.isPending}
          onDecide={(approved, final, choice) =>
            decide.mutate({ id: approval.id, approved, final, choice })
          }
        />
      ))}
    </ListCard>
  );
}

/**
 * One waiting step. Its own component so the draft lives in state keyed by the
 * approval: the queue is read again every half minute, and a refetch must never
 * overwrite what the approver is typing.
 */
function StepApprovalRow({
  approval,
  deciding,
  onDecide,
}: {
  approval: WorkflowApprovalRead;
  deciding: boolean;
  onDecide: (approved: boolean, final?: string, choice?: string) => void;
}) {
  const t = useTranslations("pages.runs");
  const locale = useLocale();
  const userId = useAuthStore((s) => s.user?.id ?? null);
  const headingId = useId();
  const original = approval.proposal ?? "";
  const [draft, setDraft] = useState(original);
  const [showChanges, setShowChanges] = useState(false);
  // The diff is quadratic in the lines; it may lag a keystroke behind the editor.
  const shownDraft = useDeferredValue(draft);

  const named = approval.approver_user_ids.length > 0;
  const notYours = named && (userId === null || !approval.approver_user_ids.includes(userId));
  const unsendable = draft.trim() === "" || draft.length > MAX_PROPOSAL_CHARS;
  const heading = approval.proposal_label ?? t("stepApprovalProposal");
  const approveDisabled = deciding || notYours || (approval.editable && unsendable);
  // What goes with an approval: the edit, when there is one, whichever button is pressed.
  const edit = approval.editable && draft !== original ? draft : undefined;

  return (
    <div className="flex flex-col gap-3 px-5 py-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1.5">
          <div className="flex items-center gap-2">
            <UserCheck className="text-muted-foreground h-4 w-4 shrink-0" />
            <span className="text-sm font-medium">{approval.title}</span>
          </div>
          {approval.details !== null && (
            <p className="text-foreground/80 text-sm whitespace-pre-wrap">{approval.details}</p>
          )}
          <p className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
            <Link
              href={ROUTES.WORKFLOW_RUN_DETAIL(approval.workflow_id, approval.workflow_run_id)}
              className="underline underline-offset-2"
            >
              {approval.workflow_name}
            </Link>
            <span>{formatDate(approval.created_at, locale)}</span>
            {approval.expires_at !== null && (
              <span>
                {t("stepApprovalExpires", { at: formatDate(approval.expires_at, locale) })}
              </span>
            )}
            {named && (
              <Badge variant="outline">
                {t("stepApprovalNamed", { count: approval.approver_user_ids.length })}
              </Badge>
            )}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {approval.choices.length > 0 ? (
            approval.choices.map((choice) => (
              <Button
                key={choice.id}
                size="sm"
                disabled={approveDisabled}
                onClick={() => onDecide(true, edit, choice.id)}
              >
                <CheckCircle2 className="h-4 w-4" />
                {choice.label}
              </Button>
            ))
          ) : (
            <Button size="sm" disabled={approveDisabled} onClick={() => onDecide(true, edit)}>
              <CheckCircle2 className="h-4 w-4" />
              {t("approve")}
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            disabled={deciding || notYours}
            onClick={() => onDecide(false)}
          >
            <XCircle className="h-4 w-4" />
            {t("reject")}
          </Button>
        </div>
      </div>
      {notYours && <p className="text-muted-foreground text-xs">{t("stepApprovalNotYours")}</p>}
      {approval.editable ? (
        <div className="space-y-2">
          <h3 id={headingId} className="text-sm font-medium">
            {heading}
          </h3>
          {approval.proposal_format === "markdown" ? (
            <MarkdownEditor
              value={draft}
              onChange={setDraft}
              label={heading}
              rows={8}
              disabled={notYours}
              inertImages
            />
          ) : (
            <Textarea
              aria-labelledby={headingId}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              rows={6}
              disabled={notYours}
            />
          )}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <p
              className={cn(
                "text-xs",
                draft.length > MAX_PROPOSAL_CHARS ? "text-destructive" : "text-muted-foreground",
              )}
            >
              {t("stepApprovalLength", { count: draft.length, max: MAX_PROPOSAL_CHARS })}
            </p>
            {draft.trim() === "" && !notYours && (
              <p className="text-muted-foreground text-xs">{t("stepApprovalEmpty")}</p>
            )}
            <Button
              size="sm"
              variant="ghost"
              disabled={notYours || draft === original}
              onClick={() => setDraft(original)}
            >
              <Undo2 className="h-4 w-4" />
              {t("stepApprovalRestore")}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-expanded={showChanges}
              onClick={() => setShowChanges((shown) => !shown)}
            >
              <GitCompare className="h-4 w-4" />
              {showChanges ? t("stepApprovalHideChanges") : t("stepApprovalShowChanges")}
            </Button>
          </div>
          {showChanges && (
            <LineDiff
              before={original}
              after={shownDraft}
              identicalLabel={t("stepApprovalNoChanges")}
              unchangedLabel={(count) => t("stepApprovalUnchangedLines", { count })}
              tooLongLabel={t("stepApprovalDiffTooLong")}
            />
          )}
        </div>
      ) : (
        approval.proposal !== null && (
          <div className="space-y-1">
            <h3 className="text-sm font-medium">{heading}</h3>
            {approval.proposal_format === "markdown" ? (
              <MarkdownContent content={approval.proposal} inertImages />
            ) : (
              <p className="text-foreground/80 text-sm whitespace-pre-wrap">{approval.proposal}</p>
            )}
          </div>
        )
      )}
    </div>
  );
}

const DECISION_TONE: Record<string, string> = {
  approved: "bg-success/10 text-success",
  rejected: "bg-destructive/10 text-destructive",
};

const DECISION_LABEL: Record<string, string> = {
  approved: "decisionApproved",
  rejected: "decisionRejected",
  expired: "decisionExpired",
};

/** One workflow step's request somebody already answered, or that lapsed, as a line of the record. */
export function DecidedWorkflowApproval({ approval }: { approval: WorkflowApprovalRead }) {
  const t = useTranslations("pages.runs");
  const locale = useLocale();
  const labelKey = DECISION_LABEL[approval.status];
  const chosen = approval.choices.find((choice) => choice.id === approval.choice);

  return (
    <li className="px-5 py-3">
      <div className="flex items-center gap-3">
        <UserCheck className="text-muted-foreground size-5 shrink-0" aria-hidden />
        <Link
          href={ROUTES.WORKFLOW_RUN_DETAIL(approval.workflow_id, approval.workflow_run_id)}
          className="min-w-0 flex-1 truncate text-sm hover:underline"
        >
          <span className="font-medium">{approval.workflow_name}</span>
          <span className="text-muted-foreground"> · </span>
          {approval.title}
        </Link>
        <span
          className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
            DECISION_TONE[approval.status] ?? "bg-muted text-muted-foreground",
          )}
        >
          {labelKey ? t(labelKey) : approval.status}
        </span>
        {approval.choice !== null && (
          <Badge variant="outline">{chosen?.label ?? approval.choice}</Badge>
        )}
        {approval.edited && <Badge variant="outline">{t("stepApprovalEdited")}</Badge>}
      </div>
      {approval.note !== null && (
        <p className="text-foreground/80 mt-1 truncate pl-8 text-sm" title={approval.note}>
          {approval.note}
        </p>
      )}
      <p className="text-muted-foreground mt-1 pl-8 text-xs">
        {formatDate(approval.decided_at ?? approval.created_at, locale)}
      </p>
    </li>
  );
}
