"use client";

import type { ComponentProps } from "react";
import { ChartNoAxesCombined } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { PassRateChart } from "./pass-rate-chart";

/** A compact overview above the run history, present once there is a measured result. */
export function EvalTrend({
  className,
  ...props
}: Omit<ComponentProps<typeof PassRateChart>, "compact"> & { className?: string }) {
  const t = useTranslations("evals");
  if (!props.lines.some((line) => line.points.length > 0)) return null;
  return (
    <section
      aria-label={t("trendTitle")}
      className={cn("border-border space-y-3 border-b p-4 sm:p-5", className)}
    >
      <h3 className="flex items-center gap-2 text-sm font-medium">
        <ChartNoAxesCombined className="text-muted-foreground size-4" aria-hidden />
        {t("trendTitle")}
      </h3>
      <PassRateChart {...props} compact />
    </section>
  );
}
