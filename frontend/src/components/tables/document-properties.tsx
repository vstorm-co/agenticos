"use client";

import { useLocale, useTranslations } from "next-intl";
import { RecordSourceBadge } from "./record-source-badge";
import { formatDateTime } from "@/lib/utils";
import type { RecordRead } from "@/types/tables";

export type DocumentMetadata = Pick<
  RecordRead,
  "created_at" | "updated_at" | "created_by" | "updated_by" | "created_source" | "updated_source"
>;

/** System properties come from the record, never from editable Markdown. */
export function DocumentProperties({ metadata }: { metadata?: DocumentMetadata }) {
  const t = useTranslations("tables.markdown");
  const locale = useLocale();
  const dates = [
    ["createdAt", metadata?.created_at],
    ["updatedAt", metadata?.updated_at ?? metadata?.created_at],
  ] as const;
  return (
    <div className="shrink-0 space-y-3 border-b p-4">
      <dl className="grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
        {dates.map(([label, date]) => (
          <div
            key={label}
            className="flex flex-wrap items-baseline justify-between gap-2 sm:flex-col sm:items-start sm:gap-1"
          >
            <dt className="text-muted-foreground">{t(label)}</dt>
            <dd>{date ? formatDateTime(date, locale) : t("onCreation")}</dd>
          </div>
        ))}
        <div className="flex min-w-0 items-baseline justify-between gap-2 sm:flex-col sm:items-start sm:gap-1">
          <dt className="text-muted-foreground shrink-0">{t("createdBy")}</dt>
          <dd className="truncate" title={metadata?.created_by ?? undefined}>
            <RecordSourceBadge
              source={metadata?.created_source}
              principalId={metadata?.created_by}
              fallback={t("automatic")}
            />
          </dd>
        </div>
        <div className="flex min-w-0 items-baseline justify-between gap-2 sm:flex-col sm:items-start sm:gap-1">
          <dt className="text-muted-foreground shrink-0">{t("updatedBy")}</dt>
          <dd className="max-w-full min-w-0">
            <RecordSourceBadge
              source={metadata?.updated_source ?? metadata?.created_source}
              principalId={metadata?.updated_by ?? metadata?.created_by}
              fallback={t("automatic")}
            />
          </dd>
        </div>
      </dl>
    </div>
  );
}
