"use client";

import { NativeDisclosure } from "@/components/ui/native-disclosure";
import { MarkdownContent } from "@/components/chat/markdown-content";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEvalCases, useEvalComparison, useEvalRun } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";
import type { CaseFlip, EvalCase } from "@/types/eval-runs";
import { Details, StateBadge } from "./widgets";

/**
 * Changed held-out questions, each marked newly fixed or newly broken. Only a change
 * the repeat answers confirmed counts in the verdict; the rest wait under their own heading.
 */
export function ChangedAnswers({
  runId,
  agentId,
  flips,
  baselineId,
  candidateId,
  attributions,
  preview = false,
  baselineRunId = runId,
}: {
  preview?: boolean;
  baselineRunId?: string;
  runId: string;
  agentId: string;
  flips: CaseFlip[];
  baselineId: string;
  candidateId: string;
  attributions: Record<string, string>;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const { cases, error, isLoading } = useEvalCases(runId, {
    caseIds: flips.slice(0, 100).map((flip) => flip.case_id),
    limit: 50,
  });
  const baseline = useEvalCases(baselineRunId, {
    caseIds: flips.slice(0, 100).map((flip) => flip.case_id),
    limit: 50,
  });
  if (error || baseline.error)
    return <p role="alert">{getErrorMessage(error ?? baseline.error, tErrors)}</p>;
  if (isLoading || baseline.isLoading) return <p role="status">{t("loading")}</p>;
  const byCase = new Map(flips.map((flip) => [flip.case_id, flip]));
  const ordered = flips.flatMap((flip) => cases.filter((item) => item.case_id === flip.case_id));
  const confirmed = ordered.filter((item) => byCase.get(item.case_id)?.confirmed);
  const pending = ordered.filter((item) => !byCase.get(item.case_id)?.confirmed);
  const row = (item: EvalCase, index: number) => (
    <ChangedRow
      key={item.case_id}
      item={{
        ...item,
        attempts: [
          ...item.attempts,
          ...(baseline.cases.find((before) => before.case_id === item.case_id)?.attempts ?? []),
        ],
      }}
      flip={byCase.get(item.case_id)!.flip}
      confirmed={byCase.get(item.case_id)!.confirmed}
      baselineId={baselineId}
      candidateId={candidateId}
      attributions={attributions}
      initiallyOpen={preview && index === 0}
      preview={preview}
    />
  );
  return (
    <div className="space-y-3">
      <div className={preview ? "divide-border divide-y" : "space-y-3"}>{confirmed.map(row)}</div>
      {pending.length > 0 && (
        <NativeDisclosure className="rounded-lg border p-3">
          <summary className="cursor-pointer text-sm font-medium">
            {t("notConfirmedYet", { count: pending.length })}
          </summary>
          <div className="mt-3 space-y-3">{pending.map(row)}</div>
        </NativeDisclosure>
      )}
      <Link className="text-sm underline" href={`/agents/${agentId}/evals/${runId}`}>
        {t("openCheck")}
      </Link>
    </div>
  );
}

function ChangedRow({
  item,
  flip,
  confirmed,
  baselineId,
  candidateId,
  attributions,
  initiallyOpen,
  preview,
}: {
  preview: boolean;
  initiallyOpen: boolean;
  item: EvalCase;
  flip: CaseFlip["flip"];
  confirmed: boolean;
  baselineId: string;
  candidateId: string;
  attributions: Record<string, string>;
}) {
  const t = useTranslations("improvement");
  const tStatus = useTranslations("evals.cases.flip");
  const before = item.attempts.find((a) => a.arm_id === baselineId && a.attempt === 0);
  const after = item.attempts.find((a) => a.arm_id === candidateId && a.attempt === 0);
  return (
    <Details
      initiallyOpen={initiallyOpen}
      row={preview}
      className="@container"
      summary={
        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <span className="min-w-0 flex-1 basis-64 break-words">{item.input}</span>
          {confirmed ? (
            <StateBadge tone={flip === "regression" ? "bad" : "good"}>
              {tStatus(flip === "regression" ? "regression" : "fixed", { confirmed: "true" })}
            </StateBadge>
          ) : (
            <StateBadge tone="neutral" className="bg-transparent">
              {tStatus(flip === "regression" ? "regression" : "fixed", { confirmed: "false" })}
            </StateBadge>
          )}
        </span>
      }
    >
      <div className="grid gap-4 @2xl:grid-cols-2">
        {[
          { label: t("before"), value: before?.answer },
          { label: t("after"), value: after?.answer },
        ].map((v) => (
          <div key={v.label} className="bg-background/50 min-w-0 rounded-lg p-4">
            <p className="text-muted-foreground text-xs">{v.label}</p>
            <div className="prose-sm mt-2 text-sm leading-relaxed wrap-anywhere">
              <MarkdownContent content={v.value ?? t("unavailableAnswer")} inertImages />
            </div>
          </div>
        ))}
      </div>
      <NativeDisclosure className="text-muted-foreground text-sm">
        <summary className="cursor-pointer">{t("technicalDetails")}</summary>
        <div className="mt-2 space-y-2">
          {after?.score?.results.map((grade, index) => (
            <p key={index} className="text-muted-foreground text-sm">
              {t("graderSaid", { reason: grade.reason })}
            </p>
          ))}
        </div>
      </NativeDisclosure>
      {(!preview || Object.keys(attributions).length > 0) && (
        <NativeDisclosure className="text-muted-foreground text-sm">
          <summary className="cursor-pointer">{t("whichChange")}</summary>
          {Object.keys(attributions).length === 0 ? (
            <p className="text-muted-foreground">{t("notAttributed")}</p>
          ) : (
            Object.values(attributions).map((id, index) => (
              <ChangeCause key={id} caseId={item.case_id} runId={id} number={index + 1} />
            ))
          )}
        </NativeDisclosure>
      )}
    </Details>
  );
}
function ChangeCause({ caseId, runId, number }: { caseId: string; runId: string; number: number }) {
  const t = useTranslations("improvement");
  const { run, error: runError } = useEvalRun(runId);
  const { comparison, error } = useEvalComparison(runId, {
    live: run?.status === "queued" || run?.status === "running",
  });
  const item = comparison?.cases.find((c) => c.case_id === caseId);
  return (
    <p className="text-muted-foreground">
      {t(
        error ||
          runError ||
          comparison?.verdict === "invalid" ||
          (run && !["queued", "running", "completed"].includes(run.status))
          ? "attributionFailed"
          : !comparison
            ? "attributionWorking"
            : item && !item.confirmed && (item.flip === "regression" || item.flip === "fixed")
              ? "attributionUnconfirmed"
              : item?.flip === "regression"
                ? "changeBroke"
                : item?.flip === "fixed"
                  ? "changeFixed"
                  : "changeUnchanged",
        { number },
      )}
    </p>
  );
}
