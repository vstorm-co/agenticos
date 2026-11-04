"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  Badge,
  Button,
  Checkbox,
  Input,
  Label,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui";
import { useTable } from "@/hooks";
import { qk } from "@/lib/query-keys";
import { queryRecords } from "@/lib/tables-api";
import type { ColumnDef, ColumnTypeName, LinkedRecord, RecordRead } from "@/types/tables";

/** Records found per search: enough to choose from, few enough to read. */
const FOUND = 20;
/** The types a record is named by, its first live column of one - the service's rule. */
const NAMED_BY: ReadonlySet<ColumnTypeName> = new Set([
  "text",
  "email",
  "url",
  "phone",
  "long_text",
]);

/** A record as a link names it: its first text value, its external id, or its id's head. */
export function recordName(record: RecordRead, columns: ColumnDef[]): string {
  const named = columns.find((column) => !column.archived && NAMED_BY.has(column.type));
  const value = named ? record.values[named.id] : null;
  if (typeof value === "string" && value.trim()) return value;
  return record.external_id ?? record.id.slice(0, 8);
}

/**
 * A `link` cell: the linked records as chips, and a popover to find records of
 * the linked table by what they say and tick them on or off. Each change is
 * written as it is made, as a multi-select's is.
 */
export function LinkCell({
  id,
  column,
  value,
  links,
  onChange,
  disabled,
}: {
  id?: string;
  column: ColumnDef;
  value: string[];
  /** The linked records' names, as the record was read. */
  links: LinkedRecord[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("tables.cells");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  // Records ticked since the cell was read, named from the search they were found in.
  const [picked, setPicked] = useState<Record<string, string>>({});
  const tableId = column.link_table_id ?? null;
  const { table } = useTable(open ? tableId : null);
  const query = { search: search.trim() || null, limit: FOUND };
  const { data, isLoading } = useQuery({
    queryKey: qk.tables.records(tableId ?? "", { link: query }),
    queryFn: () => queryRecords(tableId as string, query),
    enabled: open && tableId !== null,
  });
  const names: Record<string, string> = {
    ...Object.fromEntries(links.map((linked) => [linked.id, linked.label])),
    ...picked,
  };

  const toggle = (record: RecordRead) => {
    if (value.includes(record.id)) {
      onChange(value.filter((linked) => linked !== record.id));
      return;
    }
    setPicked({ ...picked, [record.id]: recordName(record, table?.columns ?? []) });
    onChange([...value, record.id]);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          disabled={disabled}
          className="h-auto min-h-9 w-full flex-wrap justify-start gap-1 py-1.5"
        >
          {value.length === 0 ? (
            <span className="text-muted-foreground">{t("noLinks")}</span>
          ) : (
            value.map((linked) => (
              <Badge key={linked} variant="secondary" className="max-w-40 truncate font-normal">
                {names[linked] ?? t("unnamedLink")}
              </Badge>
            ))
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 space-y-2" align="start">
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t("findRecord")}
          aria-label={t("findRecord")}
        />
        <div className="max-h-64 space-y-1 overflow-y-auto">
          {isLoading ? (
            <p className="text-muted-foreground py-2 text-sm">{t("finding")}</p>
          ) : (data?.items ?? []).length === 0 ? (
            <p className="text-muted-foreground py-2 text-sm">{t("noRecordsFound")}</p>
          ) : (
            (data?.items ?? []).map((record) => (
              <div key={record.id} className="flex items-center gap-2 py-0.5">
                <Checkbox
                  id={`${id}-${record.id}`}
                  checked={value.includes(record.id)}
                  onCheckedChange={() => toggle(record)}
                  disabled={disabled}
                />
                <Label htmlFor={`${id}-${record.id}`} className="truncate font-normal">
                  {recordName(record, table?.columns ?? [])}
                </Label>
              </div>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
