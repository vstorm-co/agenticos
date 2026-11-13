"use client";

import { useTranslations } from "next-intl";

import {
  readTableAnswer,
  titleColumn,
  type TableCall,
  type TableCallQuery,
} from "@/lib/table-tool-calls";
import type { ColumnDef, RecordRead, TableRead } from "@/types/tables";

import { useCellText } from "./table-call-data";

/** Enough rows to recognize what a page held; the table itself has the rest. */
const SHOWN = 10;
/** Columns too long for one line of a transcript: the article, never its status. */
const LONG = new Set(["long_text", "rich_text"]);

/** The title column, then each short column the query filtered or sorted on. */
function shownColumns(query: TableCallQuery, table: TableRead): ColumnDef[] {
  const title = titleColumn(table.columns);
  const named = [...query.filters.map((filter) => filter.column_id), query.sort?.by];
  const picked = table.columns.filter(
    (column) => column !== title && named.includes(column.id) && !LONG.has(column.type),
  );
  return title === null ? picked : [title, ...picked];
}

function Records({
  query,
  table,
  records,
  hasMore,
}: {
  query: TableCallQuery;
  table: TableRead;
  records: RecordRead[];
  hasMore: boolean;
}) {
  const t = useTranslations("chat.tools.tableCall");
  const cellText = useCellText();
  const columns = shownColumns(query, table);
  return (
    <div className="space-y-1.5">
      <p className="text-muted-foreground text-xs">
        {t("found", { count: records.length })}
        {hasMore && ` · ${t("hasMore")}`}
      </p>
      {records.length > 0 && columns.length > 0 && (
        <div className="border-foreground/10 overflow-x-auto rounded-lg border">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                {columns.map((column) => (
                  <th key={column.id} className="px-2 py-1 text-left font-medium">
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {records.slice(0, SHOWN).map((record) => (
                <tr key={record.id} className="border-foreground/5 border-t">
                  {columns.map((column) => (
                    <td key={column.id} className="max-w-64 truncate px-2 py-1">
                      {cellText(column, record.values[column.id] ?? null)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {records.length > SHOWN && (
        <p className="text-muted-foreground text-xs">
          {t("moreRows", { count: records.length - SHOWN })}
        </p>
      )}
    </div>
  );
}

/**
 * What a table call answered, read through the table. Nothing for a call still
 * running or an answer of another shape - the raw view keeps those.
 */
export function TableCallAnswerView({
  call,
  table,
  result,
}: {
  call: TableCall;
  table: TableRead;
  result: unknown;
}) {
  const t = useTranslations("chat.tools.tableCall");
  const cellText = useCellText();
  const answer = result === undefined ? null : readTableAnswer(call.tool, result);
  if (answer === null) return null;
  if (answer.kind === "records") {
    // Only a query answers with a page, and every query call carries one.
    return (
      <Records
        query={call.query!}
        table={table}
        records={answer.records}
        hasMore={answer.hasMore}
      />
    );
  }
  if (answer.kind === "exists") {
    return <p className="text-xs">{t(answer.exists ? "exists" : "missing")}</p>;
  }
  if (answer.kind === "deleted") return <p className="text-xs">{t("deleted")}</p>;
  const title = titleColumn(table.columns);
  const label = title === null ? "" : cellText(title, answer.record.values[title.id] ?? null);
  return (
    <p className="text-xs">
      {label === ""
        ? t("recordUntitled", { revision: answer.record.revision })
        : t("record", { title: label, revision: answer.record.revision })}
    </p>
  );
}
