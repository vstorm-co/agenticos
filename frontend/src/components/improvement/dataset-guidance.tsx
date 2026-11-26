"use client";

import { useId } from "react";
import { useLocale, useTranslations } from "next-intl";
import type { HelperGuidance } from "@/types/improvement";

/** The dataset's guidance the helper reads below the platform's rules, and who last changed it. */
export function DatasetGuidance({ guidance }: { guidance: HelperGuidance }) {
  const id = useId();
  const t = useTranslations("improvement.guidance");
  const locale = useLocale();
  const date = guidance.updated_at
    ? new Date(guidance.updated_at).toLocaleDateString(locale)
    : null;
  const who = guidance.updated_by_name
    ? "named"
    : guidance.updated_by_former_member
      ? "former"
      : "unknown";
  return (
    <section className="space-y-2 rounded-lg border p-4" aria-labelledby={id}>
      <h3 id={id} className="text-sm font-medium">
        {t("title")}
      </h3>
      <p className="text-muted-foreground text-xs leading-5">{t("hint")}</p>
      <p className="bg-muted/40 max-h-40 overflow-y-auto rounded-md border p-3 text-xs leading-5 whitespace-pre-wrap">
        {guidance.text}
      </p>
      {(who !== "unknown" || date) && (
        <p className="text-muted-foreground text-xs">
          {date
            ? t("changedOn", { who, name: guidance.updated_by_name ?? "", date })
            : t("changed", { who, name: guidance.updated_by_name ?? "" })}
        </p>
      )}
    </section>
  );
}
