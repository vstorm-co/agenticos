"use client";

import Link from "next/link";
import { Table2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { parseTableCall, type TableCall } from "@/lib/table-tool-calls";
import type { ToolCall } from "@/types";
import type { CellValue, TableRead } from "@/types/tables";

import { TableCallAnswerView } from "./table-call-answer";
import { useCallTable, useCellText } from "./table-call-data";
import { TableCallQueryView } from "./table-call-query";
import { GenericToolResult } from "./generic";
import { platformCallError } from "./platform-objects";

function Values({ values, table }: { values: Record<string, CellValue>; table: TableRead }) {
  const cellText = useCellText();
  return (
    <dl className="grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
      {Object.entries(values).map(([id, value]) => {
        const column = table.columns.find((candidate) => candidate.id === id);
        return (
          <div key={id} className="contents">
            <dt className="text-muted-foreground truncate">
              {column?.label ?? <span className="font-mono">{id}</span>}
            </dt>
            <dd className="text-foreground min-w-0 break-words">{cellText(column, value)}</dd>
          </div>
        );
      })}
    </dl>
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
      <Link
        href={`/tables/${encodeURIComponent(table.id)}`}
        className="text-foreground hover:text-primary inline-flex max-w-full items-center gap-1.5 text-xs font-medium"
      >
        <Table2 className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
        <span className="truncate">{table.name}</span>
      </Link>
      {call.query !== null && <TableCallQueryView query={call.query} table={table} />}
      {call.externalId !== null && (
        <p className="text-muted-foreground text-xs">{t("externalId", { id: call.externalId })}</p>
      )}
      {call.values !== null && Object.keys(call.values).length > 0 && (
        <Values values={call.values} table={table} />
      )}
    </div>
  );
}

/** The approval card's account of a parked table write, or nothing for any other tool. */
export function TableApprovalSummary({
  toolName,
  args,
}: {
  toolName: string;
  args: Record<string, unknown>;
}) {
  const call = parseTableCall(toolName, args);
  // Only a table call reads a table: every other approval stays free of queries.
  return call === null ? null : <ParkedTableCall call={call} />;
}

function ParkedTableCall({ call }: { call: TableCall }) {
  const table = useCallTable(call);
  return table === null ? null : <TableCallSummary call={call} table={table} />;
}

/**
 * A platform table call: what it asked, then what it found or wrote.
 *
 * Falls back to the generic view - the arguments as sent - whenever the table
 * cannot be read: on a hosted page, while it loads, or for a reader without
 * access to it. An error answer keeps the generic view too, which shows it whole.
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
  if (call === null || table === null || platformCallError(toolCall) !== null) {
    return <GenericToolResult toolCall={toolCall} resultText={resultText} />;
  }
  return (
    <div className="space-y-3 py-1">
      <TableCallSummary call={call} table={table} />
      <TableCallAnswerView call={call} table={table} result={toolCall.result} />
    </div>
  );
}
