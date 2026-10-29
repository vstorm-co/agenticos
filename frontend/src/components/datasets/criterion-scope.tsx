"use client";

import { useTranslations } from "next-intl";
import { Checkbox } from "@/components/ui";

interface CriterionScopeProps {
  tags: string[];
  groups: { tags: string[]; cases: number }[];
  total: number;
  disabled: boolean;
  onChange: (tags: string[]) => void;
}

/** A criterion applies to every case or any selected tag; overlapping tags count a case once. */
export function CriterionScope({ tags, groups, total, disabled, onChange }: CriterionScopeProps) {
  const t = useTranslations("datasets.scoring");
  const available = [...new Set([...groups.flatMap((group) => group.tags), ...tags])].sort();
  const count =
    tags.length === 0
      ? total
      : groups
          .filter((group) => group.tags.some((tag) => tags.includes(tag)))
          .reduce((sum, group) => sum + group.cases, 0);
  return (
    <fieldset disabled={disabled} className="space-y-2">
      <legend className="text-muted-foreground text-xs">{t("criterionScope")}</legend>
      <label className="flex items-center gap-2 text-xs">
        <Checkbox
          checked={tags.length === 0}
          disabled={disabled || available.length === 0}
          onCheckedChange={(checked) => onChange(checked ? [] : available.slice(0, 1))}
        />
        {t("criterionEveryCase")}
      </label>
      <div className="flex flex-wrap gap-3">
        {available.map((tag) => (
          <label key={tag} className="flex items-center gap-1.5 text-xs">
            <Checkbox
              checked={tags.includes(tag)}
              disabled={disabled}
              onCheckedChange={(checked) =>
                onChange(checked ? [...tags, tag] : tags.filter((value) => value !== tag))
              }
            />
            {tag}
          </label>
        ))}
      </div>
      <p className="text-muted-foreground text-xs">{t("criterionCoverage", { count, total })}</p>
    </fieldset>
  );
}
