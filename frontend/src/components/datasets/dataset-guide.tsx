"use client";

import { useState } from "react";
import {
  ArrowRight,
  Check,
  ChevronDown,
  ClipboardCheck,
  FlaskConical,
  ListChecks,
  Route,
  Scale,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { datasetNextStep } from "./dataset-journey";
import { OPTION_TONES } from "@/lib/table-option-colors";
import { cn } from "@/lib/utils";
import type { Dataset } from "@/types/datasets";

const STEPS = [
  { id: "cases", icon: ListChecks, tone: "blue" },
  { id: "grading", icon: Scale, tone: "purple" },
  { id: "evals", icon: FlaskConical, tone: "green" },
  { id: "review", icon: ClipboardCheck, tone: "yellow" },
] as const;

export type DatasetStep = (typeof STEPS)[number]["id"];

export function DatasetGuide({
  dataset,
  tab,
  canViewRuns,
  onTab,
}: {
  dataset: Dataset;
  tab: string;
  canViewRuns: boolean;
  onTab: (tab: DatasetStep) => void;
}) {
  const t = useTranslations("datasets.journey");
  const [open, setOpen] = useState(true);
  const next = datasetNextStep(dataset);
  return (
    <section className="bg-card rounded-xl border" aria-label={t("title")}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="focus-visible:ring-ring flex w-full items-center gap-2 rounded-xl px-4 py-3 text-left text-sm focus-visible:ring-2"
      >
        <Route className="text-muted-foreground size-4" aria-hidden />
        <span className="flex-1 font-medium">{t("title")}</span>
        {!open && (
          <span className="text-muted-foreground hidden text-xs sm:block">{t(`next.${next}`)}</span>
        )}
        <ChevronDown
          className={cn("text-muted-foreground size-4 transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>
      {open && (
        <div className="space-y-3 px-4 pb-4">
          <ol className="grid grid-cols-2 gap-2 xl:grid-cols-4">
            {STEPS.filter((step) => step.id !== "evals" || canViewRuns).map((step, index) => {
              const done =
                (step.id === "cases" && next !== "cases") ||
                (step.id === "grading" && next === "evals");
              const Icon = done ? Check : step.icon;
              return (
                <li key={step.id}>
                  <button
                    type="button"
                    onClick={() => onTab(step.id)}
                    aria-current={tab === step.id ? "step" : undefined}
                    className={cn(
                      "hover:bg-accent/40 focus-visible:ring-ring flex h-full w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors focus-visible:ring-2",
                      tab === step.id ? "border-foreground/25 bg-accent/30" : "border-transparent",
                    )}
                  >
                    <span
                      className={cn(
                        "flex size-8 shrink-0 items-center justify-center rounded-lg",
                        OPTION_TONES[done ? "green" : step.tone],
                      )}
                    >
                      <Icon className="size-4" aria-hidden />
                    </span>
                    <span className="min-w-0 space-y-1">
                      <span className="block text-xs font-semibold">
                        {t(`step.${step.id}`, { number: index + 1 })}
                      </span>
                      <span className="text-muted-foreground hidden text-xs leading-relaxed sm:block">
                        {t(`hint.${step.id}`)}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
          {tab !== next && (next !== "evals" || (canViewRuns && dataset.can_run)) && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
              <p className="text-muted-foreground text-xs">{t(`guidance.${next}`)}</p>
              <Button size="sm" variant="outline" onClick={() => onTab(next)}>
                {t(`next.${next}`)}
                <ArrowRight className="size-3.5" aria-hidden />
              </Button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
