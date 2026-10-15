"use client";

import { useState } from "react";
import { Lightbulb } from "lucide-react";
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
  Textarea,
} from "@/components/ui";
import { useAiAssistance } from "@/hooks/use-organizations";
import { usePermissions } from "@/hooks/use-permissions";
import { useSetScoring } from "@/hooks/use-scoring";
import { getErrorMessage } from "@/lib/api-error";
import { scoringProblem } from "@/lib/scoring";
import type { CaseCheck, Dataset } from "@/types/datasets";
import { Perm } from "@/types/permissions";
import type { DatasetScoring, ReviewSelect } from "@/types/scoring";
import { AiAssistanceNotice } from "./ai-assistance-notice";
import { CreateJudgeDialog } from "./create-judge-dialog";
import { GradingCard } from "./grading-card";
import { JudgeSettings } from "./judge-settings";
import { ScorerRow } from "./scorer-row";

/** The default checks' shape, shown in the empty box. Code, not copy: it is what is typed. */
const DEFAULTS_EXAMPLE = '[{"type": "max_cost_usd", "value": 0.05}]';

type Part = keyof DatasetScoring;
const PASSES: Part[] = ["checks", "trajectory"];
const JUDGING: Part[] = ["judge", "reference"];
const REVIEW: Part[] = ["review"];

const shown = (checks: CaseCheck[]) => (checks.length ? JSON.stringify(checks, null, 2) : "");

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
export function GradingPanel({ dataset }: { dataset: Dataset }) {
  const t = useTranslations("datasets.scoring");
  const tErrors = useTranslations("errors");
  const save = useSetScoring(dataset.id);
  const { can } = usePermissions();
  const { enabled: aiEnabled } = useAiAssistance();
  const stored = dataset.scoring;
  const [draft, setDraft] = useState<DatasetScoring>(stored);
  const [defaults, setDefaults] = useState(shown(stored.checks.defaults));
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
    (parts.includes("checks") && defaults !== shown(stored.checks.defaults));
  const unusable = (parts: Part[]) => scoringProblem(merged(stored, draft, parts));
  const problem = scoringProblem(draft);

  async function submit(parts: Part[]) {
    let next = merged(stored, draft, parts);
    if (parts.includes("checks")) {
      let parsed: unknown;
      try {
        parsed = defaults.trim() === "" ? [] : JSON.parse(defaults);
      } catch {
        parsed = null;
      }
      if (!Array.isArray(parsed)) {
        setDefaultsProblem(t("defaultsNotJson"));
        return;
      }
      setDefaultsProblem(null);
      next = { ...next, checks: { ...next.checks, defaults: parsed as CaseCheck[] } };
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
          onChange={(next) => set("checks", { ...draft.checks, ...next })}
          disabled={disabled}
        >
          <FormField
            htmlFor="scoring-defaults"
            label={t("defaults")}
            error={defaultsProblem ?? undefined}
          >
            <Textarea
              id="scoring-defaults"
              value={defaults}
              onChange={(event) => setDefaults(event.target.value)}
              placeholder={DEFAULTS_EXAMPLE}
              className="font-mono text-xs"
              rows={3}
              disabled={disabled}
            />
          </FormField>
        </ScorerRow>
        <ScorerRow
          label={t("scorer.trajectory")}
          hint={t("trajectoryHint")}
          enabled={draft.trajectory.enabled}
          mustPass={draft.trajectory.required}
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
