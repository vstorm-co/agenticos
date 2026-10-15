"use client";

import { useEffect, useState } from "react";
import { Lightbulb, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAiAssistance } from "@/hooks/use-organizations";
import { usePermissions } from "@/hooks/use-permissions";
import { useSetScoring } from "@/hooks/use-scoring";
import { getErrorMessage } from "@/lib/api-error";
import { scoringProblem, ungradedCases } from "@/lib/scoring";
import type { Dataset } from "@/types/datasets";
import { Perm } from "@/types/permissions";
import type { DatasetScoring, ReviewSelect } from "@/types/scoring";
import { AiAssistanceNotice } from "./ai-assistance-notice";
import { CaseChecksEditor } from "./case-checks-editor";
import { checkDraft, checksOf, type CheckDraft } from "./case-form";
import { CreateJudgeDialog } from "./create-judge-dialog";
import { GradingCard } from "./grading-card";
import { JudgeSettings } from "./judge-settings";
import { ScorerRow } from "./scorer-row";

type Part = keyof DatasetScoring;
const PASSES: Part[] = ["checks", "trajectory"];
const JUDGING: Part[] = ["judge", "reference"];
const REVIEW: Part[] = ["review"];

/** The draft's `parts` over what is stored: what saving one card sends. */
function merged(stored: DatasetScoring, draft: DatasetScoring, parts: Part[]): DatasetScoring {
  return { ...stored, ...Object.fromEntries(parts.map((part) => [part, draft[part]])) };
}

/**
 * How a dataset's cases are graded, in three cards each saved on its own: when a
 * case passes, which judge grades it and how, and what waits for a person.
 *
 * The rules and the expected tool calls cost nothing; the judge and the reference
 * comparison are runs of the judge, refused while AI assistance is off. Scores
 * already kept keep the configuration they were graded with.
 */
export function GradingPanel({
  dataset,
  onDirtyChange,
}: {
  dataset: Dataset;
  /** Told whether any card holds a change not yet saved, so the page can say so. */
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const t = useTranslations("datasets.scoring");
  const tDatasets = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const save = useSetScoring(dataset.id);
  const { can } = usePermissions();
  const { enabled: aiEnabled } = useAiAssistance();
  const stored = dataset.scoring;
  const [draft, setDraft] = useState<DatasetScoring>(stored);
  const [defaults, setDefaults] = useState<CheckDraft[]>(stored.checks.defaults.map(checkDraft));
  const [defaultsProblem, setDefaultsProblem] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const canEdit = dataset.can_edit;
  const disabled = !canEdit || save.isPending;
  // The judge and the reference comparison are model runs, so they stay as stored
  // and cannot be changed while the organization has AI assistance off.
  const modelBacked = disabled || aiEnabled === false;
  const set = <K extends Part>(key: K, value: DatasetScoring[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const dirty = (parts: Part[]) =>
    parts.some((part) => JSON.stringify(draft[part]) !== JSON.stringify(stored[part])) ||
    (parts.includes("checks") &&
      JSON.stringify(defaults) !== JSON.stringify(stored.checks.defaults.map(checkDraft)));
  const unusable = (parts: Part[]) => scoringProblem(merged(stored, draft, parts));
  const problem = scoringProblem(draft);
  const unsaved = dirty(PASSES) || dirty(JUDGING) || dirty(REVIEW);
  const ungraded = ungradedCases(draft, dataset.stats, defaults.length);
  const of = (count: number) => t("coverage", { count, total: dataset.case_count });

  useEffect(() => onDirtyChange?.(unsaved), [onDirtyChange, unsaved]);
  // A tab closing or a reload would drop the drafts; the browser asks first.
  useEffect(() => {
    if (!unsaved) return;
    const hold = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", hold);
    return () => window.removeEventListener("beforeunload", hold);
  }, [unsaved]);

  async function submit(parts: Part[]) {
    let next = merged(stored, draft, parts);
    if (parts.includes("checks")) {
      const read = checksOf(defaults);
      if (read.problems.length > 0) {
        setDefaultsProblem(tDatasets(read.problems[0]!));
        return;
      }
      setDefaultsProblem(null);
      next = { ...next, checks: { ...next.checks, defaults: read.checks } };
    }
    try {
      await save.mutateAsync(next);
      toast.success(t("saved"));
    } catch (failure) {
      toast.error(getErrorMessage(failure, tErrors));
    }
  }

  const unreferenced =
    canEdit &&
    aiEnabled !== false &&
    dataset.stats.with_reference > 0 &&
    !draft.reference.enabled &&
    !stored.reference.enabled;

  return (
    <div className="space-y-4" data-tour="datasets-grading">
      <AiAssistanceNotice />
      {canEdit && problem !== null && (
        <p role="alert" className="text-destructive text-sm">
          {t(problem)}
        </p>
      )}
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
        <div className="bg-muted/50 flex flex-wrap items-center gap-3 rounded-xl border p-4 text-sm">
          <Lightbulb className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
          <p className="min-w-0 flex-1">
            {t("suggestReference", { count: dataset.stats.with_reference })}
          </p>
          <Button
            size="sm"
            variant="outline"
            onClick={() => set("reference", { ...draft.reference, enabled: true })}
          >
            {t("suggestReferenceAction")}
          </Button>
        </div>
      )}

      <GradingCard
        title={t("passes.title")}
        description={t("passes.description")}
        dirty={dirty(PASSES)}
        canSave={!disabled && unusable(PASSES) === null}
        onSave={() => void submit(PASSES)}
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
            <CaseChecksEditor checks={defaults} onChange={setDefaults} />
            {defaultsProblem && <p className="text-destructive text-xs">{defaultsProblem}</p>}
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
        description={t("judgeCard.description")}
        dirty={dirty(JUDGING)}
        canSave={!modelBacked && unusable(JUDGING) === null}
        onSave={() => void submit(JUDGING)}
        tour="datasets-grading-judge"
      >
        <JudgeSettings
          referenceCoverage={of(dataset.stats.with_reference)}
          judge={draft.judge}
          stored={stored.judge}
          reference={draft.reference}
          onJudge={(judge) => set("judge", judge)}
          onReference={(reference) => set("reference", reference)}
          disabled={modelBacked}
          onCreate={canEdit && can(Perm.agentsEdit) ? () => setCreating(true) : undefined}
        />
      </GradingCard>

      <GradingCard
        title={t("reviewCard.title")}
        description={t("reviewCard.description")}
        dirty={dirty(REVIEW)}
        canSave={!disabled}
        onSave={() => void submit(REVIEW)}
      >
        <FormField htmlFor="scoring-review" label={t("reviewSelect")}>
          <Select
            value={draft.review.select}
            onValueChange={(select) => set("review", { select: select as ReviewSelect })}
            disabled={disabled}
          >
            <SelectTrigger id="scoring-review">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">{t("review.none")}</SelectItem>
              <SelectItem value="failed">{t("review.failed")}</SelectItem>
              <SelectItem value="all">{t("review.all")}</SelectItem>
            </SelectContent>
          </Select>
        </FormField>
      </GradingCard>

      <p className="text-muted-foreground text-xs">{t("mustPassRule")}</p>

      {creating && (
        <CreateJudgeDialog
          dataset={dataset}
          onOpenChange={setCreating}
          onCreated={(updated) =>
            set("judge", { ...draft.judge, agent_id: updated.scoring.judge.agent_id })
          }
        />
      )}
    </div>
  );
}
