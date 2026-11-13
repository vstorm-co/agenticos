"use client";

import { useLocale, useTranslations } from "next-intl";

import { recordCellText } from "@/lib/format-cell-value";
import { formatDateTime } from "@/lib/utils";
import type { ColumnDef, RecordRead } from "@/types/tables";

import { RecordSourceBadge } from "./record-source-badge";

/**
 * What a field holds now, beside the edit a revision conflict refused: the value
 * someone else wrote, who wrote the record last and when - so the reader decides
 * between theirs and their own with both in view.
 */
export function RecordConflictNow({ column, record }: { column: ColumnDef; record: RecordRead }) {
  const t = useTranslations("tables.sheet");
  const tCells = useTranslations("tables.cells");
  const locale = useLocale();
  const value = recordCellText(
    column,
    record,
    (on) => (on ? tCells("true") : tCells("false")),
    locale,
  );
  const preview = value.length > 300 ? `${value.slice(0, 300)}…` : value;
  const who = (
    <RecordSourceBadge
      source={record.updated_source}
      principalId={record.updated_by}
      fallback={t("conflictSomeone")}
    />
  );
  return (
    <p className="text-foreground break-words" role="status" data-testid="conflict-now">
      {t.rich(record.updated_at ? "conflictNow" : "conflictNowUntimed", {
        value: preview || t("conflictEmpty"),
        time: record.updated_at ? formatDateTime(record.updated_at, locale) : "",
        who: () => who,
      })}
    </p>
  );
}
