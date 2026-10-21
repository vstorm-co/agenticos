"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Lock } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import { useAgent } from "@/hooks/use-agents";
import { useDataset } from "@/hooks/use-datasets";
import { isLive, useEvalComparison, useEvalRun } from "@/hooks/use-eval-runs";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { useAuthStore } from "@/stores/auth-store";
import { ArmsTable } from "./arms-table";
import { ALL, CaseTable, FilterSelect } from "./case-table";
import { ComparisonCard } from "./comparison-card";
import { sideName } from "./names";
import { StartEvalDialog } from "./start-eval-dialog";
import { VerdictHeader } from "./verdict-header";

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
  const tc = useTranslations("common");
  const { run, isLoading, error, refetch, cancel } = useEvalRun(runId);
  const { agent } = useAgent(agentId);
  const { dataset } = useDataset(run?.dataset_id ?? "");
  const me = useAuthStore((state) => state.user?.id);
  // Testing the draft again starts a run of it on the same dataset, which these three decide.
  const canTestAgain =
    agent?.can_run === true && agent.can_edit === true && dataset?.can_run === true;
  const candidates = run?.arms.filter((arm) => arm.role === "candidate") ?? [];
  const [arm, setArm] = useState<string | null>(null);
  const [tag, setTag] = useState<string | null>(null);
  const [broken, setBroken] = useState(false);
  const [testingAgain, setTestingAgain] = useState(false);
  // `?case=` names one case to open - how Activity hands a case back to its run.
  const params = useSearchParams();
  const asked = params.get("case");
  const router = useRouter();
  const [only, setOnly] = useState<string | null>(asked);
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

  if (isLoading || misplaced) return <LoadingState variant="skeleton-cards" rows={3} />;
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

  const tags = [...new Set(run.arms.flatMap((item) => Object.keys(item.by_tag)))].sort();
  const candidate = candidates.find((item) => item.id === focus);
  const brokenIds = (comparison?.cases ?? [])
    .filter((item) => item.flip === "regression")
    .map((item) => item.case_id);

  return (
    <div className="space-y-6">
      <Link
        href={`${ROUTES.AGENTS}/${agentId}?tab=evals`}
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        {t("back")}
      </Link>
      <VerdictHeader
        agentId={agentId}
        run={run}
        candidate={candidate}
        canPublish={agent?.can_publish === true}
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
        onRetryComparison={!live && comparisonError ? () => void refetchComparison() : undefined}
        onShowBroken={() => {
          setOnly(null);
          setBroken(true);
          cases.current?.scrollIntoView?.({ behavior: "smooth" });
        }}
      />
      {(run.excluded_case_ids?.length ?? 0) > 0 && (
        <p role="note" className="text-muted-foreground text-sm">
          {t("excludedEvidence", { count: run.excluded_case_ids?.length ?? 0 })}
        </p>
      )}
      {(candidate?.skill_ids?.length ?? 0) > 0 ? (
        <Link href={ROUTES.SKILLS} className="text-sm underline">
          {t("backToSkillChange")}
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
                  {t("sideModel", { name: sideName(item, t), model: item.model_label })}
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
      />
      {!live && comparison && (
        <ComparisonCard agentId={agentId} comparison={comparison} tag={tag} />
      )}
      {testingAgain && (
        <StartEvalDialog
          agentId={agentId}
          datasetId={run.dataset_id}
          target="compare"
          onOpenChange={setTestingAgain}
        />
      )}
      <div ref={cases}>
        <CaseTable
          run={run}
          arm={focus}
          comparison={live ? undefined : comparison}
          tag={tag}
          caseIds={only !== null ? [only] : broken ? brokenIds.slice(0, CASE_IDS) : null}
          brokenTotal={brokenIds.length}
          opened={only}
          onShowAll={() => {
            setBroken(false);
            setOnly(null);
          }}
        />
      </div>
    </div>
  );
}
