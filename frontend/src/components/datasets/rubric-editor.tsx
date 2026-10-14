"use client";

import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, IconButton, Input, Switch, Textarea } from "@/components/ui";
import type { RubricCriterion } from "@/types/scoring";

interface RubricEditorProps {
  criteria: RubricCriterion[];
  onChange: (criteria: RubricCriterion[]) => void;
  disabled?: boolean;
}

/** The judge's rubric: named criteria, each graded on the scale and required or not. */
export function RubricEditor({ criteria, onChange, disabled = false }: RubricEditorProps) {
  const t = useTranslations("datasets.scoring");
  const change = (index: number, patch: Partial<RubricCriterion>) =>
    onChange(criteria.map((item, at) => (at === index ? { ...item, ...patch } : item)));

  return (
    <div className="space-y-3">
      {criteria.map((criterion, index) => (
        <div key={index} className="space-y-2 rounded-md border p-3">
          <div className="flex items-center gap-2">
            <Input
              value={criterion.name}
              onChange={(event) => change(index, { name: event.target.value })}
              placeholder={t("criterionNamePlaceholder")}
              aria-label={t("criterionName")}
              disabled={disabled}
              maxLength={80}
            />
            <label className="flex shrink-0 items-center gap-2 text-xs">
              <Switch
                checked={criterion.required}
                onCheckedChange={(required) => change(index, { required })}
                aria-label={t("required")}
                disabled={disabled}
              />
              {t("required")}
            </label>
            <IconButton
              aria-label={t("removeCriterion")}
              disabled={disabled}
              onClick={() => onChange(criteria.filter((_, at) => at !== index))}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
            </IconButton>
          </div>
          <Textarea
            value={criterion.description}
            onChange={(event) => change(index, { description: event.target.value })}
            placeholder={t("criterionDescriptionPlaceholder")}
            aria-label={t("criterionDescription")}
            disabled={disabled}
            rows={2}
          />
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
