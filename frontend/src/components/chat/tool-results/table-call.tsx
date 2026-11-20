"use client";

import Link from "next/link";
import { Fragment, type ReactNode } from "react";
import { Table2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { parseTableCall, titleColumn, type TableCall } from "@/lib/table-tool-calls";
import type { ToolCall } from "@/types";
import type { CellValue, TableRead } from "@/types/tables";

import { TableCallAnswerView } from "./table-call-answer";
import { useCallRecord, useCallTable, useCellText, useRecordText } from "./table-call-data";
import { TableCallQueryView } from "./table-call-query";
import { GenericToolResult } from "./generic";
import { platformCallError } from "./platform-objects";

/** One labelled line - "Table", "Column", "Value" - so a reader never guesses which is which. */
function Line({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-muted-foreground">{label}</dt>
      {/* Bounded: the whole of a long value stays in the raw arguments. */}
      <dd className="text-foreground line-clamp-4 min-w-0 break-words">{children}</dd>
    </div>
  );
}

function Values({ values, table }: { values: Record<string, CellValue>; table: TableRead }) {
  const t = useTranslations("chat.tools.tableCall");
  const cellText = useCellText();
  return (
    <>
      {Object.entries(values).map(([id, value]) => {
        const column = table.columns.find((candidate) => candidate.id === id);
        return (
          <Fragment key={id}>
            <Line label={t("column")}>
              {column?.label ?? <span className="font-mono">{id}</span>}
            </Line>
            <Line label={t("value")}>{cellText(column, value)}</Line>
          </Fragment>
        );
      })}
    </>
  );
}

/**
 * The record a call reads, changes or deletes, by its title where it has one -
 * a pending deletion otherwise names nothing it would remove - and by its id
 * where it has none or cannot be read.
 */
function RecordLine({ call, table }: { call: TableCall; table: TableRead }) {
  const t = useTranslations("chat.tools.tableCall");
  const recordText = useRecordText();
  const record = useCallRecord(call);
  const title = titleColumn(table.columns);
  const label = record === null || title === null ? "" : recordText(title, record);
  return (
    <Line label={t("recordLabel")}>
      {label === "" ? <span className="font-mono">{call.recordId}</span> : label}
    </Line>
  );
}

/**
 * What a table call asks, in the table's own names: its conditions, its order,
 * the cells it writes. Null while the table is unknown - the arguments are then
 * the only honest account of the call, and the caller shows those.
 */
export function TableCallSummary({ call, table }: { call: TableCall; table: TableRead }) {
  const t = useTranslations("chat.tools.tableCall");
  return (
    <div className="space-y-2">
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
        <Line label={t("table")}>
          <Link
            href={`/tables/${encodeURIComponent(table.id)}`}
            className="hover:text-primary inline-flex max-w-full items-center gap-1.5 font-medium"
          >
            <Table2 className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
            <span className="truncate">{table.name}</span>
          </Link>
        </Line>
        {call.recordId !== null && <RecordLine call={call} table={table} />}
        {call.values !== null && <Values values={call.values} table={table} />}
      </dl>
      {call.query !== null && <TableCallQueryView query={call.query} table={table} />}
      {call.externalId !== null && (
        <p className="text-muted-foreground text-xs">{t("externalId", { id: call.externalId })}</p>
      )}
    </div>
  );
}

/**
 * A table call in the table's labels, above the raw arguments a surface keeps
 * showing - an approval card, a run's timeline. Nothing for any other tool, or
 * while the table cannot be read; `result` adds what the call answered.
 */
export function TableCallReadout({
  toolName,
  args,
  result,
  fallback = null,
}: {
  toolName: string;
  args: unknown;
  result?: unknown;
  /** Shown instead while the table cannot be read, so a card never loses its target. */
  fallback?: ReactNode;
}) {
  const call = parseTableCall(toolName, args);
  // Only a table call reads a table: every other tool stays free of queries.
  return call === null ? null : (
    <ReadableTableCall call={call} result={result} fallback={fallback} />
  );
}

function ReadableTableCall({
  call,
  result,
  fallback,
}: {
  call: TableCall;
  result: unknown;
  fallback: ReactNode;
}) {
  const table = useCallTable(call);
  if (table === null) return fallback;
  return (
    <div className="space-y-3">
      <TableCallSummary call={call} table={table} />
      <TableCallAnswerView call={call} table={table} result={result} />
    </div>
  );
}

/**
 * A platform table call: what it asked, then what it found or wrote.
 *
 * Falls back to the generic view - the arguments as sent - whenever the table
 * cannot be read: on a hosted page, while it loads, or for a reader without
 * access to it. A failed call or an error answer keeps the generic view too,
 * which shows the failure whole.
 */
export function TableToolResult({
  toolCall,
  toolName,
  resultText,
}: {
  toolCall: ToolCall;
  toolName: string;
  resultText: string;
}) {
  const call = parseTableCall(toolName, toolCall.args);
  const table = useCallTable(call);
  if (
    call === null ||
    table === null ||
    toolCall.status === "error" ||
    platformCallError(toolCall) !== null
  ) {
    return <GenericToolResult toolCall={toolCall} resultText={resultText} />;
  }
  return (
    <div className="space-y-3 py-1">
      <TableCallSummary call={call} table={table} />
      <TableCallAnswerView call={call} table={table} result={toolCall.result} />
    </div>
  );
}
