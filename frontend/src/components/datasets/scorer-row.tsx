"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { Checkbox } from "@/components/ui";

interface ScorerRowProps {
  label: string;
  hint: string;
  enabled: boolean;
  /** Whether a case must pass it; absent for a scorer whose criteria say so each. */
  mustPass?: boolean;
  /** How many of the dataset's cases hold what it reads, as a sentence. */
  coverage?: string;
  onChange: (next: { enabled: boolean; required?: boolean }) => void;
  disabled: boolean;
  children?: ReactNode;
}

/** One scorer: whether it runs, whether a case must pass it, and its settings while on. */
export function ScorerRow({
  label,
  hint,
  enabled,
  mustPass,
  coverage,
  onChange,
  disabled,
  children,
}: ScorerRowProps) {
  const t = useTranslations("datasets.scoring");
  return (
    <div className="space-y-3 border-b pb-4 last:border-b-0 last:pb-0">
      <div className="flex flex-wrap items-start gap-3">
        <label className="flex min-w-0 flex-1 basis-full cursor-pointer items-start gap-3 sm:basis-0">
          <Checkbox
            className="mt-0.5"
            checked={enabled}
            onCheckedChange={(next) => onChange({ enabled: next === true, required: mustPass })}
            aria-label={label}
            disabled={disabled}
          />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-medium">{label}</span>
            <span className="text-muted-foreground block text-sm">{hint}</span>
            {coverage && (
              <span className="text-muted-foreground mt-1 block text-xs">{coverage}</span>
            )}
          </span>
        </label>
        {mustPass !== undefined && enabled && (
          <label className="ml-7 flex items-center gap-2 text-xs sm:ml-0">
            <Checkbox
              checked={mustPass}
              onCheckedChange={(next) => onChange({ enabled, required: next === true })}
              aria-label={t("mustPassNamed", { scorer: label })}
              disabled={disabled}
            />
            {t("mustPass")}
          </label>
        )}
      </div>
      {enabled && children}
    </div>
  );
}
