"use client";

import { useCallback, useEffect, useState, type SetStateAction } from "react";
import { ArrowRight, Lightbulb, ListChecks, Scale, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { sameJson } from "@/lib/canonical-json";
import { Button } from "@/components/ui";
import { useSetScoring } from "@/hooks/use-scoring";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { getErrorMessage } from "@/lib/api-error";
import { scoringProblem, ungradedCases } from "@/lib/scoring";
import type { CaseCheck, Dataset } from "@/types/datasets";
import type { DatasetScoring } from "@/types/scoring";
import { CaseChecksEditor } from "./case-checks-editor";
import { checkDraft, checksOf, sameCheck, type CheckDraft } from "./case-form";
import { GradingCard } from "./grading-card";
import { GradingSaveBar } from "./grading-save-bar";
import { JudgeSettings } from "./judge-settings";
import { ScorerRow } from "./scorer-row";

type Part = keyof DatasetScoring;
const PASSES: Part[] = ["checks", "trajectory"];
const JUDGING: Part[] = ["judge", "reference"];

/** What a kept copy of the panel's unsaved change holds. */
export interface GradingCopy {
  draft: DatasetScoring;
  defaults: CheckDraft[];
}

/** Dataset grading: deterministic rules and model-backed criteria, saved together. */
export function GradingPanel({
  dataset,
  onDirtyChange,
  localCopy,
  restore,
  onContinue,
}: {
  dataset: Dataset;
  onContinue?: () => void;
  /** Told whether any card holds a change not yet saved, so the page can say so. */
  onDirtyChange?: (dirty: boolean) => void;
  /** Where an unsaved change is kept in this browser, and the version it is made on. */
  localCopy?: { key: string; base: number };
  /** A kept change to bring back; `at` tells one restore from the next. */
  restore?: { value: GradingCopy; at: number };
}) {
  const t = useTranslations("datasets.scoring");
  const journey = useTranslations("datasets.journey");
  const tDatasets = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const save = useSetScoring(dataset.id);
  const stored = dataset.scoring;
  const [{ draft, defaults }, setCopy] = useState<GradingCopy>(() => ({
    draft: stored,
    defaults: stored.checks.defaults.map(checkDraft),
  }));
  const setDraft = useCallback(
    (next: SetStateAction<DatasetScoring>) =>
      setCopy((current) => ({
        ...current,
        draft: typeof next === "function" ? next(current.draft) : next,
      })),
    [],
  );
  const setDefaults = useCallback(
    (next: SetStateAction<CheckDraft[]>) =>
      setCopy((current) => ({
        ...current,
        defaults: typeof next === "function" ? next(current.defaults) : next,
      })),
    [],
  );
  const [defaultsProblem, setDefaultsProblem] = useState<string | null>(null);
  const [restored, setRestored] = useState<number | null>(null);
  if (restore !== undefined && restore.at !== restored) {
    setRestored(restore.at);
    setCopy(restore.value);
  }
  const canEdit = dataset.can_edit;
  const disabled = !canEdit || save.isPending;
  const modelBacked = disabled;
  const set = <K extends Part>(key: K, value: DatasetScoring[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const dirty = (parts: Part[]) =>
    parts.some((part) => !sameJson(draft[part], stored[part])) ||
    (parts.includes("checks") && !sameJson(defaults, stored.checks.defaults.map(checkDraft)));
  const problem = scoringProblem(draft);
  const unsaved = dirty(PASSES) || dirty(JUDGING);
  const ungraded = ungradedCases(draft, dataset.stats, defaults.length);
  const of = (count: number) => t("coverage", { count, total: dataset.case_count });
  // A rule suggested under a criterion joins the checks every case gets, and turns them on.
  const rules = {
    has: (check: CaseCheck) => defaults.some((kept) => sameCheck(kept, checkDraft(check))),
    onAdd: disabled
      ? undefined
      : (check: CaseCheck) => {
          setDefaults((current) => [...current, checkDraft(check)]);
          setDraft((current) => ({ ...current, checks: { ...current.checks, enabled: true } }));
        },
  };

  useEffect(() => onDirtyChange?.(unsaved), [onDirtyChange, unsaved]);
  useUnsavedChanges(`grading:${dataset.id}`, {
    dirty: unsaved,
    save: problem === null ? submit : undefined,
    discard,
    copy: localCopy && { ...localCopy, value: { draft, defaults } satisfies GradingCopy },
  });

  async function submit(): Promise<boolean> {
    const read = checksOf(defaults);
    if (read.problems.length > 0) {
      setDefaultsProblem(tDatasets(read.problems[0]!));
      return false;
    }
    setDefaultsProblem(null);
    const next = { ...draft, checks: { ...draft.checks, defaults: read.checks } };
    try {
      const sent = { draft, defaults };
      const saved = await save.mutateAsync(next);
      setCopy((current) =>
        sameJson(current, sent)
          ? { draft: saved.scoring, defaults: saved.scoring.checks.defaults.map(checkDraft) }
          : current,
      );
      toast.success(t("saved"));
      return true;
    } catch (failure) {
      toast.error(getErrorMessage(failure, tErrors));
      return false;
    }
  }

  function discard() {
    setDraft(stored);
    setDefaults(stored.checks.defaults.map(checkDraft));
    setDefaultsProblem(null);
  }

  const unreferenced =
    canEdit &&
    dataset.stats.with_reference > 0 &&
    !draft.reference.enabled &&
    !stored.reference.enabled;

  return (
    <div className="flex flex-1 flex-col gap-4" data-tour="datasets-grading">
      {canEdit && problem === null && ungraded > 0 && (
        <p
          role="status"
          className="flex items-start gap-2 text-sm text-amber-700 dark:text-amber-400"
        >
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {t("ungraded", { count: ungraded })}
        </p>
      )}
      {unreferenced && (
        <div className="bg-muted/50 flex flex-col gap-3 rounded-xl border p-4 text-sm sm:flex-row sm:items-center">
          <div className="flex min-w-0 flex-1 items-start gap-3">
            <Lightbulb className="text-muted-foreground mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <p className="min-w-0">
              {t("suggestReference", { count: dataset.stats.with_reference })}
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="w-full shrink-0 sm:w-auto"
            onClick={() => set("reference", { ...draft.reference, enabled: true })}
          >
            {t("suggestReferenceAction")}
          </Button>
        </div>
      )}

      <div className="grid items-stretch gap-4 xl:grid-cols-2">
        <GradingCard
          title={t("passes.title")}
          icon={ListChecks}
          tone="blue"
          description={t("passes.description")}
          dirty={dirty(PASSES)}
        >
          <ScorerRow
            label={t("scorer.check")}
            hint={t("checksHint")}
            enabled={draft.checks.enabled}
            mustPass={draft.checks.required}
            coverage={of(dataset.stats.with_checks)}
            onChange={(next) => set("checks", { ...draft.checks, ...next })}
            disabled={disabled}
          >
            <fieldset className="space-y-2" disabled={disabled}>
              <legend className="text-sm font-medium">{t("defaults")}</legend>
              <CaseChecksEditor checks={defaults} onChange={setDefaults} disabled={disabled} />
              {defaultsProblem && <p className="text-destructive-ink text-xs">{defaultsProblem}</p>}
            </fieldset>
          </ScorerRow>
          <ScorerRow
            label={t("scorer.trajectory")}
            hint={t("trajectoryHint")}
            enabled={draft.trajectory.enabled}
            mustPass={draft.trajectory.required}
            coverage={of(dataset.stats.with_tool_calls)}
            onChange={(next) => set("trajectory", { ...draft.trajectory, ...next })}
            disabled={disabled}
          />
        </GradingCard>

        <GradingCard
          title={t("judgeCard.title")}
          icon={Scale}
          tone="purple"
          description={t("judgeCard.description")}
          dirty={dirty(JUDGING)}
          tour="datasets-grading-judge"
        >
          <JudgeSettings
            tagGroups={dataset.stats.tag_groups}
            totalCases={dataset.case_count}
            referenceCoverage={of(dataset.stats.with_reference)}
            counterExampleCoverage={of(dataset.stats.with_counter_example)}
            judge={draft.judge}
            defaultInstructions={dataset.helper_defaults?.judge}
            stored={stored.judge}
            reference={draft.reference}
            onJudge={(judge) => set("judge", judge)}
            onReference={(reference) => set("reference", reference)}
            disabled={modelBacked}
            rules={rules}
          />
        </GradingCard>
      </div>
      <p className="text-muted-foreground text-xs">{t("mustPassRule")}</p>

      {!unsaved && problem === null && ungraded === 0 && dataset.case_count > 0 && onContinue && (
        <div className="bg-card flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4">
          <p className="text-muted-foreground text-sm">{journey("guidance.evals")}</p>
          <Button onClick={onContinue}>
            {journey("next.evals")}
            <ArrowRight className="size-4" aria-hidden />
          </Button>
        </div>
      )}
      {canEdit && unsaved && (
        <GradingSaveBar
          problem={problem === null ? null : t(problem)}
          saving={save.isPending}
          onSave={() => void submit()}
          onDiscard={discard}
        />
      )}
    </div>
  );
}
