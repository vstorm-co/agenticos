"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

/** Keep fields mounted so hidden execution settings still validate and retain edits. */
export function RoutineOptions({
  children,
  invalid = false,
}: {
  children: ReactNode;
  invalid?: boolean;
}) {
  const t = useTranslations("triggers");
  return (
    <details className="group rounded-lg border" open={invalid ? true : undefined}>
      <summary
        data-tour="routine-advanced"
        className="marker:text-muted-foreground cursor-pointer px-4 py-3 text-sm font-medium"
      >
        {t("advancedOptions")}
        <span className="text-muted-foreground mt-1 block text-xs font-normal">
          {t("advancedOptionsHint")}
        </span>
      </summary>
      <div className="space-y-4 border-t p-4">{children}</div>
    </details>
  );
}
