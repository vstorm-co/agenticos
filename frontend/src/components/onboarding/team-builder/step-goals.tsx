"use client";

import { useTranslations } from "next-intl";
import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

interface StepGoalsProps {
  goals: string[];
  details: string;
  onChange: (fields: { goals?: string[]; details?: string }) => void;
}

const GOAL_KEYS = [
  "support",
  "docs",
  "releases",
  "research",
  "contracts",
  "automation",
  "incidents",
  "content",
  "data",
  "meetings",
] as const;

export function StepGoals({ goals, details, onChange }: StepGoalsProps) {
  const t = useTranslations("onboardingTeam");

  const toggleGoal = (goalKey: string) => {
    if (goals.includes(goalKey)) {
      onChange({ goals: goals.filter((g) => g !== goalKey) });
    } else {
      onChange({ goals: [...goals, goalKey] });
    }
  };

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{t("step2Title")}</h2>
        <p className="text-muted-foreground mt-1 text-sm leading-relaxed">{t("step2Subtitle")}</p>
      </div>

      <div className="space-y-3">
        <label className="text-foreground text-sm font-medium">{t("goalsLabel")}</label>
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          {GOAL_KEYS.map((key) => {
            const selected = goals.includes(key);
            return (
              <button
                key={key}
                type="button"
                onClick={() => toggleGoal(key)}
                className={cn(
                  "border-border bg-card hover:border-brand/40 flex items-center justify-between rounded-xl border p-3.5 text-left transition-all",
                  selected && "border-brand bg-brand/5 ring-brand/20 ring-1",
                )}
              >
                <span className="text-foreground text-xs font-medium">{t(`goals.${key}`)}</span>
                <div
                  className={cn(
                    "flex size-4 items-center justify-center rounded border transition-colors",
                    selected ? "border-brand bg-brand text-brand-foreground" : "border-border",
                  )}
                >
                  {selected && <Check className="size-3" />}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="space-y-2">
        <label htmlFor="workflow-details" className="text-foreground text-sm font-medium">
          {t("detailsLabel")}
        </label>
        <textarea
          id="workflow-details"
          rows={3}
          value={details}
          onChange={(e) => onChange({ details: e.target.value })}
          placeholder={t("detailsPlaceholder")}
          className="border-border bg-card text-foreground placeholder:text-muted-foreground focus:border-brand focus:ring-brand/20 w-full resize-none rounded-xl border p-3.5 text-sm transition-all focus:ring-1 focus:outline-none"
        />
      </div>
    </div>
  );
}
