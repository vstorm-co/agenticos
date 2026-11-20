"use client";

import { Check, Inbox, Search, Sun } from "lucide-react";
import { useTranslations } from "next-intl";
import { APP_CONNECTION_GOALS, type AppConnectionGoal } from "@/lib/app-connection-journey";
import { cn } from "@/lib/utils";

const ICONS = { day: Sun, inbox: Inbox, answers: Search };

export function ConnectionGoals({
  goal,
  onChange,
}: {
  goal: AppConnectionGoal;
  onChange: (goal: AppConnectionGoal) => void;
}) {
  const t = useTranslations("appConnections");
  return (
    <div className="space-y-3" data-tour="app-connection-goals">
      <h2 className="text-lg font-medium">{t("chooseGoal")}</h2>
      <p className="text-muted-foreground text-sm">{t("goalHint")}</p>
      <div className="grid gap-3 md:grid-cols-3">
        {APP_CONNECTION_GOALS.map((value) => {
          const Icon = ICONS[value];
          return (
            <button
              key={value}
              type="button"
              aria-pressed={goal === value}
              onClick={() => onChange(value)}
              className={cn(
                "border-border hover:bg-muted/50 flex min-w-0 items-start gap-3 rounded-xl border p-4 text-left transition-colors",
                goal === value && "border-foreground bg-muted/50",
              )}
            >
              <Icon className="mt-0.5 size-5 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{t(`goals.${value}.title`)}</span>
                <span className="text-muted-foreground mt-1 block text-sm">
                  {t(`goals.${value}.description`)}
                </span>
              </span>
              {goal === value && <Check className="size-4 shrink-0" aria-hidden />}
            </button>
          );
        })}
      </div>
    </div>
  );
}
