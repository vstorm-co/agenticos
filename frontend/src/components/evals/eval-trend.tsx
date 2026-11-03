"use client";

import { useState, type ComponentProps } from "react";
import { ChevronDown, ChartNoAxesCombined } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { PassRateChart } from "./pass-rate-chart";

/** Results stay visible first; a trend is available when the reader wants context. */
export function EvalTrend(props: ComponentProps<typeof PassRateChart>) {
  const t = useTranslations("evals");
  const [open, setOpen] = useState(false);
  return (
    <section className="border-border border-t p-4">
      <Button variant="ghost" size="sm" aria-expanded={open} onClick={() => setOpen(!open)}>
        <ChartNoAxesCombined className="size-4" />
        {t("trendTitle")}
        <ChevronDown className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} />
      </Button>
      {open && (
        <div className="pt-4">
          <PassRateChart {...props} />
        </div>
      )}
    </section>
  );
}
