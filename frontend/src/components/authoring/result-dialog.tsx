"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useEvalCases, useEvalRun } from "@/hooks/use-eval-runs";
import { DIALOG_BODY, DIALOG_BROAD, DIALOG_COLUMN } from "@/lib/dialog-sizes";
import { expectedEffect } from "@/lib/authoring-text";
import { ROUTES } from "@/lib/constants";
import type { AuthoringRequest, Hunk, SuggestionBatch } from "@/types/authoring";
import { EvidenceList } from "./evidence-list";
import { FieldDiff } from "./field-change";
import { RejectedChanges } from "./rejected-changes";

/** One request owns the notice, so observing a new request cannot reopen an old result. */
export function AuthoringResultNotice({
  request,
  batch,
  canReadRuns,
}: {
  request: AuthoringRequest;
  batch: SuggestionBatch | null;
  canReadRuns: boolean;
}) {
  const t = useTranslations("authoring.result");
  const working = request.status === "queued" || request.status === "running";
  const [observedWorking, setObservedWorking] = useState(working);
  const [dismissed, setDismissed] = useState(false);
  const [requested, setRequested] = useState(false);
  // A guarded adjustment to changed input, preserving the transition across query refreshes.
  if (working && !observedWorking) setObservedWorking(true);
  if (request.status !== "completed" || request.kind !== "improve") return null;
  const matchingBatch = batch?.request_id === request.id ? batch : null;
  const open = requested || (observedWorking && !dismissed);
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setRequested(true)}>
        {t("open")}
      </Button>
      {open && (
        <AuthoringResultDialog
          request={request}
          batch={matchingBatch}
          canReadRuns={canReadRuns}
          onOpenChange={(next) => {
            if (!next) {
              setRequested(false);
              setDismissed(true);
            }
          }}
        />
      )}
    </>
  );
}

export function AuthoringResultDialog({
  request,
  batch,
  canReadRuns,
  onOpenChange,
}: {
  request: AuthoringRequest;
  batch: SuggestionBatch | null;
  canReadRuns: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("authoring.result");
  const tb = useTranslations("authoring.batch");
  const changes = batch?.hunks ?? [];
  const effect = batch ? expectedEffect(batch, (count) => tb("fromEvidence", { count })) : "";
  const checkId = batch?.check_eval_run_ids.at(-1);
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={`${DIALOG_BROAD} ${DIALOG_COLUMN}`}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>
            {changes.length > 0
              ? t("counts", {
                  proposed: request.report?.proposed ?? changes.length,
                  recorded: request.report?.recorded ?? changes.length,
                  reviewed: request.evidence.runs ?? 0,
                })
              : t("empty")}
          </DialogDescription>
        </DialogHeader>
        <div className={`${DIALOG_BODY} space-y-5`}>
          {request.evidence.problem_answers !== undefined && (
            <p className="text-sm font-medium">
              {t("problems", { count: request.evidence.problem_answers })}
            </p>
          )}
          {changes.length > 0 && effect && <p className="text-sm">{effect}</p>}
          {changes.map((hunk) => (
            <ChangePreview key={hunk.id} hunk={hunk} />
          ))}
          <RejectedChanges report={request.report} />
          {changes.length === 0 && !request.report?.rejected?.length && (
            <p className="text-muted-foreground text-sm">{t("nothingToPlace")}</p>
          )}
          {canReadRuns && checkId ? (
            <CheckedAnswers runId={checkId} />
          ) : (
            changes.length > 0 && <p className="text-muted-foreground text-sm">{t("checkFirst")}</p>
          )}
        </div>
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)}>{t("close")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ChangePreview({ hunk }: { hunk: Hunk }) {
  const t = useTranslations("authoring.result");
  const ts = useTranslations("authoring.suggestion");
  const kind =
    hunk.kind === "instructions"
      ? ts("instructions")
      : hunk.kind === "tool_override"
        ? ts("tool", { tool: hunk.tool_id ?? "" })
        : t("configuration");
  const before =
    hunk.kind === "tool_override"
      ? [hunk.base_name ?? hunk.tool_id, hunk.base_description].filter(Boolean).join("\n")
      : hunk.old_text;
  const after =
    hunk.kind === "tool_override"
      ? [
          hunk.new_name ?? hunk.base_name ?? hunk.tool_id,
          hunk.new_description ?? hunk.base_description,
        ]
          .filter(Boolean)
          .join("\n")
      : hunk.new_text;
  return (
    <article className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{kind}</Badge>
        {!hunk.applies && <Badge variant="warning">{ts("stale")}</Badge>}
      </div>
      {hunk.kind === "spec_field" ? (
        <FieldDiff hunk={hunk} editing={null} onEdit={() => {}} />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {[
            { label: t("before"), text: before },
            { label: t("after"), text: after },
          ].map(({ label, text }) => (
            <div key={label} className="min-w-0 space-y-1">
              <h4 className="text-muted-foreground text-xs font-medium">{label}</h4>
              <pre className="bg-muted/40 max-h-72 overflow-auto rounded-md p-3 text-xs break-words whitespace-pre-wrap">
                {text || t("emptyPassage")}
              </pre>
            </div>
          ))}
        </div>
      )}
      <div>
        <h4 className="text-xs font-medium">{t("why")}</h4>
        <p className="text-sm">{hunk.rationale}</p>
      </div>
      <div>
        <h4 className="mb-1 text-xs font-medium">{t("basedOn")}</h4>
        <EvidenceList items={hunk.evidence} dropped={hunk.evidence_dropped} />
      </div>
    </article>
  );
}

/** Read only when a person opens results; answers stay behind runs:view. */
export function CheckedAnswers({ runId }: { runId: string }) {
  const { run, error } = useEvalRun(runId);
  const t = useTranslations("authoring.result");
  if (error)
    return (
      <p role="alert" className="text-destructive text-sm">
        {t("unavailable")}
      </p>
    );
  if (!run)
    return (
      <p role="status" className="text-muted-foreground text-sm">
        {t("loading")}
      </p>
    );
  if (run.status !== "completed")
    return <p className="text-muted-foreground text-sm">{t("checkFirst")}</p>;
  return (
    <AnswerRows
      runId={runId}
      baselineId={run.arms.find((arm) => arm.role === "baseline")?.id}
      candidateId={run.arms.find((arm) => arm.role === "candidate")?.id}
      href={`${ROUTES.AGENTS}/${run.agent_id}/evals/${runId}`}
    />
  );
}

function AnswerRows({
  runId,
  baselineId,
  candidateId,
  href,
}: {
  runId: string;
  baselineId?: string;
  candidateId?: string;
  href: string;
}) {
  const { cases, total, isLoading, error } = useEvalCases(runId, { limit: 5 });
  const t = useTranslations("authoring.result");
  if (error)
    return (
      <p role="alert" className="text-destructive text-sm">
        {t("unavailable")}
      </p>
    );
  if (isLoading)
    return (
      <p role="status" className="text-muted-foreground text-sm">
        {t("loading")}
      </p>
    );
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-medium">{t("answers")}</h3>
      {cases.map((item) => (
        <article key={item.case_id} className="space-y-2 rounded-lg border p-3">
          <p className="text-sm font-medium">{item.input}</p>
          <div className="grid gap-3 md:grid-cols-2">
            {[
              { label: t("before"), arm: baselineId },
              { label: t("after"), arm: candidateId },
            ].map(({ label, arm }) => (
              <div key={label} className="min-w-0">
                <h4 className="text-muted-foreground text-xs">{label}</h4>
                <p className="text-sm break-words whitespace-pre-wrap">
                  {item.attempts.find((attempt) => attempt.arm_id === arm && attempt.attempt === 0)
                    ?.answer ?? t("noAnswer")}
                </p>
              </div>
            ))}
          </div>
        </article>
      ))}
      {total > cases.length && (
        <p className="text-muted-foreground text-xs">
          {t("more", { count: total - cases.length })}
        </p>
      )}
      <Link className="text-sm underline underline-offset-4" href={href}>
        {t("allAnswers")}
      </Link>
    </section>
  );
}
