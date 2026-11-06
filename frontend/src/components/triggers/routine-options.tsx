"use client";

import { useEffect, useRef, type ReactNode } from "react";
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
  const details = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    // Open for a validation error without closing the user's panel once fixed.
    if (invalid && details.current) details.current.open = true;
  }, [invalid]);
  return (
    <details ref={details} className="group rounded-lg border">
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
