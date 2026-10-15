"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { Switch } from "@/components/ui";

interface ScorerRowProps {
  label: string;
  hint: string;
  enabled: boolean;
  /** Whether a case must pass it; absent for a scorer whose criteria say so each. */
  mustPass?: boolean;
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
  onChange,
  disabled,
  children,
}: ScorerRowProps) {
  const t = useTranslations("datasets.scoring");
  return (
    <div className="space-y-3 border-b pb-4 last:border-b-0 last:pb-0">
      <div className="flex flex-wrap items-start gap-3">
        <Switch
          checked={enabled}
          onCheckedChange={(next) => onChange({ enabled: next, required: mustPass })}
          aria-label={label}
          disabled={disabled}
        />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{label}</p>
          <p className="text-muted-foreground text-xs">{hint}</p>
        </div>
        {mustPass !== undefined && enabled && (
          <label className="flex items-center gap-2 text-xs">
            <Switch
              checked={mustPass}
              onCheckedChange={(next) => onChange({ enabled, required: next })}
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
