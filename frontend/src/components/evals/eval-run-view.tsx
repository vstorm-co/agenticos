"use client";

import { useEffect, useRef, useState } from "react";
import { ReviewReevaluationNote } from "@/components/evals/review-reevaluation-note";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Lock } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { PageHeader } from "@/components/dashboard/page-header";
import { BackLink } from "@/components/layout/back-link";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import { useAgent } from "@/hooks/use-agents";
import { useDataset } from "@/hooks/use-datasets";
import { useSkill } from "@/hooks/use-skills";
import { isLive, useEvalComparison, useEvalRun } from "@/hooks/use-eval-runs";
import { useUrlState } from "@/hooks/use-url-state";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { useAuthStore } from "@/stores/auth-store";
import { ArmsTable } from "./arms-table";
import { ALL, CaseTable, FilterSelect } from "./case-table";
import { ImprovementMeasurement } from "./improvement-measurement";
import { ComparisonCard } from "./comparison-card";
import { sideName, type SideCheck } from "./names";
import { StartEvalDialog } from "./start-eval-dialog";
import { VerdictHeader, type CheckStage } from "./verdict-header";

/** As many cases as the API filters on by id in one request. */
const CASE_IDS = 100;

/**
 * One eval run, verdict first: what changed and what to do about it, then each
 * side's numbers, how the two compare, and every case - over the whole dataset
 * or over the cases carrying one tag.
 */
export function EvalRunView({ agentId, runId }: { agentId: string; runId: string }) {
  const t = useTranslations("evals");
  const tErrors = useTranslations("errors");
  const tCases = useTranslations("evals.cases");
  const tNav = useTranslations("nav");
  const tc = useTranslations("common");
  const { run, isLoading, error, refetch, cancel } = useEvalRun(runId);
  const { agent } = useAgent(agentId);
  const { dataset } = useDataset(run?.dataset_id ?? "");
  const me = useAuthStore((state) => state.user?.id);
  // Testing the draft again starts a run of it on the same dataset, which these three decide.
  const canTestAgain =
    agent?.can_run === true && agent.can_edit === true && dataset?.can_run === true;
  const candidates = run?.arms.filter((arm) => arm.role === "candidate") ?? [];
  // A skill's check runs one agent on both sides, so each side is named by that agent.
  const checked = candidates[0]?.skill_ids?.[0];
  const checkId = run?.proposal_check?.skill_check_id ?? null;
  const { skill: stageSkill } = useSkill(checkId !== null && checked ? checked : null);
  const [arm, setArm] = useUrlState("arm");
  const [tag, setTag] = useUrlState("tag");
  const [brokenParam, setBrokenParam] = useUrlState("broken");
  const [testingAgain, setTestingAgain] = useState(false);
  // `?case=` names one case to open - how Activity hands a case back to its run.
  const params = useSearchParams();
  const asked = params.get("case");
  const router = useRouter();
  const [only, setOnly] = useUrlState("case");
  const cases = useRef<HTMLDivElement>(null);
  const focus = arm ?? candidates[0]?.id ?? null;
  const live = run !== undefined && isLive(run.status);
  const {
    comparison,
    error: comparisonError,
    refetch: refetchComparison,
  } = useEvalComparison(runId, {
    arm: focus,
    live,
  });
  // The run and its verdict are polled apart, so the poll that sees the run end
  // can stop the verdict's before it read the last reruns: read it once more.
  const wasLive = useRef(live);
  useEffect(() => {
    if (wasLive.current && !live) void refetchComparison();
    wasLive.current = live;
  }, [live, refetchComparison]);
  const loaded = run !== undefined;
  useEffect(() => {
    if (asked !== null && loaded) cases.current?.scrollIntoView?.({ block: "start" });
  }, [asked, loaded]);
  // Everything on the page - access, back link, testing again, publishing - is
  // read off the agent in the address, so a run of another agent moves there.
  const owner = run?.agent_id;
  const misplaced = owner !== undefined && owner !== agentId;
  useEffect(() => {
    if (!misplaced) return;
    const query = params.toString();
    router.replace(`${ROUTES.AGENTS}/${owner}/evals/${runId}${query ? `?${query}` : ""}`);
  }, [misplaced, owner, runId, params, router]);

  if (isLoading || misplaced) return <LoadingState variant="pending" />;
  if (error instanceof ApiError && error.status === 403) {
    return <EmptyState icon={Lock} title={t("noAccess.title")} description={t("noAccess.body")} />;
  }
  if (error || !run) {
    return (
      <ErrorState
        description={getErrorMessage(error, tErrors)}
        cta={{ label: tc("retry"), onClick: () => void refetch() }}
      />
    );
  }

  const comparable = comparison?.verdict !== "invalid";
  const broken = brokenParam === "1" && comparable;
  const tags = [...new Set(run.arms.flatMap((item) => Object.keys(item.by_tag)))].sort();
  const candidate = candidates.find((item) => item.id === focus);
  const check: SideCheck | null | undefined =
    run.proposal_check?.kind === "skill" && agent
      ? {
          ...run.proposal_check,
          agent: agent.name,
          current: run.arms
            .find((item) => item.role === "baseline")
            ?.skill_versions?.find((served) => served.skill_id === checked),
        }
      : run.proposal_check;
  const named = { ...run, proposal_check: check };
  const stage: CheckStage | null =
    checkId !== null && checked && agent
      ? { skillId: checked, skillName: stageSkill?.name ?? null, agent: agent.name, checkId }
      : null;
  // A sampled stage leaves the questions it did not ask out, which no change was derived from.
  const notAsked = run.proposal_check?.not_asked ?? 0;
  const fromEvidence = (run.excluded_case_ids?.length ?? 0) - notAsked;
  const brokenIds = (comparison?.cases ?? [])
    .filter((item) => item.flip === "regression")
    .map((item) => item.case_id);

  return (
    <div className="w-full min-w-0 space-y-4 pb-6">
      <BackLink
        href={`${ROUTES.AGENTS}/${agentId}?tab=evals`}
        label={t("back")}
        className="text-muted-foreground hover:text-foreground inline-flex min-h-8 items-center gap-2 text-sm"
      />
      <PageHeader
        title={t("resultTitle")}
        breadcrumbs={[
          { label: agent?.name ?? tNav("agents"), href: `${ROUTES.AGENTS}/${agentId}?tab=evals` },
          { label: run.dataset_name, href: ROUTES.DATASET_DETAIL(run.dataset_id) },
          { label: t("resultTitle") },
        ]}
        description={t("runTitle", {
          dataset: run.dataset_name,
          version: run.dataset_version,
          candidate: candidate ? sideName(candidate, t, check) : "",
        })}
        descriptionMode="summary"
      />
      {run.review && <ReviewReevaluationNote review={run.review} />}
      <VerdictHeader
        agentId={agentId}
        run={named}
        candidate={candidate}
        canPublish={agent?.can_publish === true}
        canEditDataset={dataset?.can_edit === true}
        comparison={live ? undefined : comparison}
        onCancel={
          live && (run.created_by_user_id === me || agent?.can_edit === true)
            ? () =>
                cancel.mutate(undefined, {
                  onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
                })
            : undefined
        }
        onTestAgain={canTestAgain ? () => setTestingAgain(true) : undefined}
        stage={stage}
        onRetryComparison={!live && comparisonError ? () => void refetchComparison() : undefined}
        onShowBroken={() => {
          setOnly(null);
          setBrokenParam("1");
          cases.current?.scrollIntoView?.({ behavior: "smooth" });
        }}
      />
      {run.proposal_check?.measurement && !stage && (
        <ImprovementMeasurement measurement={run.proposal_check.measurement} />
      )}
      {stage && (
        <p role="note" className="text-muted-foreground text-sm">
          {t("checkStage.pooled")}
        </p>
      )}
      {notAsked > 0 && (
        <p role="note" className="text-muted-foreground text-sm">
          {t("notAsked", { count: notAsked })}
        </p>
      )}
      {fromEvidence > 0 && (
        <p role="note" className="text-muted-foreground text-sm">
          {t("excludedEvidence", { count: fromEvidence })}
        </p>
      )}
      {stage ? null : (candidate?.skill_ids?.length ?? 0) > 0 ? (
        <Link href={ROUTES.SKILLS} className="text-sm underline">
          {t("backToSkillChange")}
        </Link>
      ) : (candidate?.context_ids?.length ?? 0) > 0 ? (
        <Link href={ROUTES.CONTEXT} className="text-sm underline">
          {t("backToContextChange")}
        </Link>
      ) : (
        candidate?.source === "explicit" && (
          <Link href={`${ROUTES.AGENTS}/${agentId}?tab=build`} className="text-sm underline">
            {t("backToSuggestions")}
          </Link>
        )
      )}
      <div className="flex flex-wrap gap-2">
        {candidates.length > 1 && (
          <Select value={focus ?? ""} onValueChange={setArm}>
            <SelectTrigger aria-label={t("compareArm")} className="w-64">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {candidates.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  {t("sideModel", { name: sideName(item, t, check), model: item.model_label })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {tags.length > 0 && (
          <FilterSelect
            label={tCases("tagFilter")}
            value={tag ?? ALL}
            onChange={(value) => setTag(value === ALL ? null : value)}
            options={[
              { value: ALL, label: tCases("allTags") },
              ...tags.map((value) => ({ value, label: `#${value}` })),
            ]}
          />
        )}
      </div>
      <ArmsTable
        agentId={agentId}
        arms={run.arms}
        tag={tag}
        live={live}
        baseline={comparison?.baseline ?? null}
        check={check}
        baselineSummary={comparison?.baseline_summary ?? null}
      />
      {!live && comparison && (
        <ComparisonCard agentId={agentId} comparison={comparison} tag={tag} check={check} />
      )}
      {testingAgain && (
        <StartEvalDialog
          agentId={agentId}
          datasetId={run.dataset_id}
          target={candidate?.source === "version" ? "version" : "compare"}
          onOpenChange={setTestingAgain}
        />
      )}
      <div ref={cases}>
        <CaseTable
          run={named}
          arm={focus}
          comparison={live || !comparable ? undefined : comparison}
          tag={tag}
          caseIds={only !== null ? [only] : broken ? brokenIds.slice(0, CASE_IDS) : null}
          brokenTotal={brokenIds.length}
          opened={only}
          onShowAll={() => {
            setBrokenParam(null);
            setOnly(null);
          }}
        />
      </div>
    </div>
  );
}
