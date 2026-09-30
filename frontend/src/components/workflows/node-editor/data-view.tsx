"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { JsonView } from "@/components/ui/json-view";
import { SHOWN_ROWS, cellText, schemaOf, tableOf } from "@/lib/workflows/step-data";
import { cn } from "@/lib/utils";

type View = "table" | "json" | "schema";
const VIEWS: View[] = ["table", "json", "schema"];

/**
 * One step's data, three ways: as rows (a list of records as a table, anything
 * else as one row), as the JSON itself, and as its fields with their types - the
 * paths a later step reads.
 */
export function DataView({ value }: { value: Record<string, unknown> }) {
  const t = useTranslations("workflows");
  const [view, setView] = useState<View>("table");

  return (
    <div className="space-y-2">
      <div
        role="group"
        aria-label={t("dataViews")}
        className="bg-muted inline-flex rounded-md p-0.5"
      >
        {VIEWS.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={view === option}
            onClick={() => setView(option)}
            className={cn(
              "rounded px-2 py-0.5 text-xs",
              view === option
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t(`dataView.${option}`)}
          </button>
        ))}
      </div>
      {view === "json" && <JsonView value={value} />}
      {view === "table" && <TableView value={value} />}
      {view === "schema" && <SchemaView value={value} />}
    </div>
  );
}

function TableView({ value }: { value: Record<string, unknown> }) {
  const t = useTranslations("workflows");
  const { columns, rows } = tableOf(value);
  if (columns.length === 0)
    return <p className="text-muted-foreground text-xs">{t("dataEmpty")}</p>;
  return (
    <div className="space-y-1">
      <div className="border-border overflow-x-auto rounded-md border">
        <table className="w-full text-xs">
          <thead className="bg-muted/50 text-muted-foreground">
            <tr>
              {columns.map((column) => (
                <th key={column} className="px-2 py-1 text-left font-medium whitespace-nowrap">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-border divide-y">
            {rows.slice(0, SHOWN_ROWS).map((row, index) => (
              <tr key={index}>
                {columns.map((column) => (
                  <td key={column} className="max-w-60 truncate px-2 py-1 align-top">
                    {cellText(row[column])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > SHOWN_ROWS && (
        <p className="text-muted-foreground text-xs">
          {t("dataMoreRows", { count: rows.length - SHOWN_ROWS })}
        </p>
      )}
    </div>
  );
}

function SchemaView({ value }: { value: Record<string, unknown> }) {
  const t = useTranslations("workflows");
  const fields = schemaOf(value);
  if (fields.length === 0) return <p className="text-muted-foreground text-xs">{t("dataEmpty")}</p>;
  return (
    <ul className="space-y-0.5 font-mono text-[11.5px]">
      {fields.map((field) => (
        <li key={field.path} className="flex justify-between gap-3">
          <span className="truncate">{field.path}</span>
          <span className="text-muted-foreground shrink-0">{field.type}</span>
        </li>
      ))}
    </ul>
  );
}
