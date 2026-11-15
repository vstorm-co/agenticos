"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
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
        className="focus-visible:ring-ring touch:min-h-11 flex cursor-pointer list-none items-start gap-2 rounded-lg px-3 py-3 text-sm font-medium outline-none focus-visible:ring-2 sm:px-4 [&::-webkit-details-marker]:hidden"
      >
        <ChevronRight
          aria-hidden
          className="text-muted-foreground mt-0.5 size-4 shrink-0 transition-transform group-open:rotate-90"
        />
        <span className="min-w-0">
          <span>{t("advancedOptions")}</span>
          <span className="text-muted-foreground mt-1 block text-xs font-normal">
            {t("advancedOptionsHint")}
          </span>
        </span>
      </summary>
      <div className="space-y-4 border-t p-3 sm:p-4">{children}</div>
    </details>
  );
}
