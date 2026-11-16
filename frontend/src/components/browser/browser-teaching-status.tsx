"use client";

import { useLocale, useTranslations } from "next-intl";
import { Badge } from "@/components/ui";
import { teachingReason } from "@/lib/browser-teaching-review";
import type { TeachingSummary } from "@/types/browser-teaching";

export function TeachingError({ error }: { error: unknown }) {
  const t = useTranslations("browserTeaching");
  const reason = teachingReason(error);
  return (
    <p role="alert" className="text-destructive text-sm">
      {reason ? t(`reason.${reason}`) : t("requestUnavailable")}
    </p>
  );
}
export function TeachingStatus({ session }: { session: TeachingSummary }) {
  const t = useTranslations("browserTeaching");
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="outline">{t(`status.${session.status}`)}</Badge>
      <Badge variant="secondary">{t(`source.${session.source}`)}</Badge>
      {session.generation_state !== "none" && (
        <span className="text-muted-foreground text-sm">
          {t(`generation.${session.generation_state}`)}
        </span>
      )}
    </div>
  );
}
export function TeachingTime({ value }: { value: string }) {
  const locale = useLocale();
  return (
    <time dateTime={value}>
      {new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(
        new Date(value),
      )}
    </time>
  );
}
