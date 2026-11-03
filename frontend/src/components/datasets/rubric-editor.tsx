"use client";

import { useId } from "react";
import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, IconButton, Input, Checkbox, FormField, Textarea } from "@/components/ui";
import type { RubricCriterion } from "@/types/scoring";
import { CriterionRule, type RuleChecks } from "./criterion-rule";
import { CriterionScope } from "./criterion-scope";

interface RubricEditorProps {
  criteria: RubricCriterion[];
  tagGroups?: { tags: string[]; cases: number }[];
  totalCases?: number;
  onChange: (criteria: RubricCriterion[]) => void;
  disabled?: boolean;
  /** The dataset's rules, under which a criterion a rule can check offers it. */
  rules?: RuleChecks;
}

/** The judge's rubric: named criteria, each graded on the scale and required or not. */
export function RubricEditor({
  criteria,
  onChange,
  disabled = false,
  tagGroups = [],
  totalCases = 0,
  rules,
}: RubricEditorProps) {
  const t = useTranslations("datasets.scoring");
  const prefix = useId();
  const change = (index: number, patch: Partial<RubricCriterion>) =>
    onChange(criteria.map((item, at) => (at === index ? { ...item, ...patch } : item)));

  return (
    <div className="space-y-3">
      <p className="text-muted-foreground text-xs">{t("yesNoHint")}</p>
      {criteria.map((criterion, index) => (
        <div key={index} className="space-y-2 rounded-md border p-3">
          <div className="flex flex-wrap items-end gap-3">
            <FormField
              htmlFor={`${prefix}-${index}-name`}
              label={t("criterionName")}
              className="min-w-0 flex-1 basis-full sm:basis-0"
            >
              <Input
                value={criterion.name}
                onChange={(event) => change(index, { name: event.target.value })}
                placeholder={t("criterionNamePlaceholder")}
                aria-label={t("criterionName")}
                disabled={disabled}
                maxLength={80}
              />
            </FormField>
            <label className="flex shrink-0 items-center gap-2 text-xs">
              <Checkbox
                checked={criterion.required}
                onCheckedChange={(required) => change(index, { required: required === true })}
                aria-label={t("mustPass")}
                disabled={disabled}
              />
              {t("mustPass")}
            </label>
            <IconButton
              aria-label={t("removeCriterion")}
              disabled={disabled}
              onClick={() => onChange(criteria.filter((_, at) => at !== index))}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
            </IconButton>
          </div>
          <CriterionScope
            tags={criterion.tags ?? []}
            groups={tagGroups}
            total={totalCases}
            disabled={disabled}
            onChange={(tags) => change(index, { tags })}
          />
          <FormField
            htmlFor={`${prefix}-${index}-description`}
            label={t("criterionDescription")}
            description={t("criterionHelp")}
          >
            <Textarea
              value={criterion.description}
              onChange={(event) => change(index, { description: event.target.value })}
              placeholder={t("criterionDescriptionPlaceholder")}
              aria-label={t("criterionDescription")}
              disabled={disabled}
              rows={3}
            />{" "}
          </FormField>

          {rules && <CriterionRule criterion={criterion} rules={rules} />}
        </div>
      ))}
      <Button
        variant="outline"
        size="sm"
        disabled={disabled || criteria.length >= 20}
        onClick={() => onChange([...criteria, { name: "", description: "", required: true }])}
      >
        <Plus className="h-4 w-4" aria-hidden />
        {t("addCriterion")}
      </Button>
    </div>
  );
}
