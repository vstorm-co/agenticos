"use client";
import { useTranslations } from "next-intl";
import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { Input, Label } from "@/components/ui";
import { useModelProviders } from "@/hooks/use-model-providers";
import { cn } from "@/lib/utils";
import type { ImprovementMode } from "@/types/improvement";

/** Training questions a search needs; the server refuses one with fewer. */
export const MIN_SEARCH_QUESTIONS = 10;

/**
 * How a session's attempts reach their changes: one proposal at a time, or a search
 * of many variants of the instructions scored on training questions. Search is
 * offered only when the dataset has enough training questions to score on.
 */
export function StartMode({
  mode,
  onModeChange,
  trainQuestions,
  budget,
  onBudgetChange,
  gradingModelId,
  onGradingModelChange,
}: {
  mode: ImprovementMode;
  onModeChange: (mode: ImprovementMode) => void;
  trainQuestions: number | null;
  budget: string;
  onBudgetChange: (budget: string) => void;
  gradingModelId: string | null;
  onGradingModelChange: (id: string | null) => void;
}) {
  const t = useTranslations("improvement.startSearch");
  const { profiles, profilesStatus } = useModelProviders();
  const tooFew = trainQuestions !== null && trainQuestions < MIN_SEARCH_QUESTIONS;
  // The search budget defaults from the first quote, so Search waits for one.
  const unpriced = trainQuestions === null;
  const options: { value: ImprovementMode; hint: string; disabled: boolean }[] = [
    { value: "steps", hint: t("stepsHint"), disabled: false },
    {
      value: "search",
      hint: tooFew
        ? t("tooFew", { count: trainQuestions, needed: MIN_SEARCH_QUESTIONS })
        : unpriced
          ? t("unpriced")
          : t("searchHint"),
      disabled: tooFew || unpriced,
    },
  ];
  return (
    <fieldset className="space-y-3" data-tour="improvement-mode">
      <legend className="mb-2 text-sm font-medium">{t("label")}</legend>
      {options.map((option) => (
        <div
          key={option.value}
          className={cn(
            "flex gap-3 rounded-lg border p-3 text-sm",
            mode === option.value && "border-primary",
            option.disabled && "opacity-60",
          )}
        >
          <input
            id={`improvement-mode-${option.value}`}
            type="radio"
            name="improvement-mode"
            value={option.value}
            checked={mode === option.value}
            disabled={option.disabled}
            onChange={() => onModeChange(option.value)}
            className="mt-1"
          />
          <label
            htmlFor={`improvement-mode-${option.value}`}
            className={cn("space-y-1", option.disabled ? "cursor-not-allowed" : "cursor-pointer")}
          >
            <span className="block font-medium">{t(option.value)}</span>
            <span className="text-muted-foreground block text-xs">{option.hint}</span>
          </label>
        </div>
      ))}
      {mode === "search" && (
        <div className="space-y-4 rounded-lg border p-3">
          <div className="space-y-1.5">
            <Label htmlFor="improvement-search-budget">{t("budget")}</Label>
            <Input
              id="improvement-search-budget"
              inputMode="decimal"
              value={budget}
              onChange={(event) => onBudgetChange(event.target.value)}
            />
            <p className="text-muted-foreground text-xs">{t("budgetHint")}</p>
          </div>
          <div className="space-y-1.5">
            <Label>{t("gradingModel")}</Label>
            <ModelProfilePicker
              compact
              profiles={profiles}
              profilesStatus={profilesStatus}
              value={gradingModelId}
              onChange={onGradingModelChange}
              emptyLabel={t("datasetJudge")}
            />
            <p className="text-muted-foreground text-xs">{t("gradingHint")}</p>
          </div>
        </div>
      )}
    </fieldset>
  );
}
