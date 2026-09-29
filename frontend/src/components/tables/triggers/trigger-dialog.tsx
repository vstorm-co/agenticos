"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { WorkflowRead } from "@/lib/workflows/types";
import {
  AUTHOR_SOURCE,
  RECORD_ID_SOURCE,
  type ColumnDef,
  type FilterOp,
  type RecordFilter,
  type TableTriggerCreate,
  type TableTriggerRead,
} from "@/types/tables";

/** The operators a filter row offers, in the order a person reaches for them. */
const OPS: FilterOp[] = [
  "eq",
  "ne",
  "contains",
  "starts_with",
  "gt",
  "gte",
  "lt",
  "lte",
  "is_null",
];

interface MappingRow {
  key: string;
  source: string;
}

interface FilterRow {
  column_id: string;
  op: FilterOp;
  value: string;
}

/** A filter row's operand as the column's type stores it - a number, a flag, text. */
export function operand(
  column: ColumnDef | undefined,
  op: FilterOp,
  raw: string,
): RecordFilter["value"] {
  if (op === "is_null") return raw !== "false";
  if (column && (column.type === "number" || column.type === "integer")) {
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : raw;
  }
  if (column?.type === "boolean") return raw === "true";
  return raw;
}

function rowsOf(trigger: TableTriggerRead | undefined): {
  filters: FilterRow[];
  mapping: MappingRow[];
} {
  return {
    filters: (trigger?.filters ?? []).map((filter) => ({
      column_id: filter.column_id,
      op: filter.op,
      value: filter.value === undefined || filter.value === null ? "" : String(filter.value),
    })),
    mapping: Object.entries(trigger?.input_mapping ?? {}).map(([key, source]) => ({ key, source })),
  };
}

interface TriggerDialogProps {
  columns: ColumnDef[];
  workflows: WorkflowRead[];
  trigger?: TableTriggerRead;
  busy?: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (body: TableTriggerCreate) => void;
}

/**
 * Set up, or change, a workflow a table runs when a record is added.
 *
 * Which workflow, which records - every filter must hold, judged on the record
 * as it was created - and what the run starts with: each payload key takes a
 * column's value, the record's author or the record's id. The workflow's live version is pinned
 * when the trigger is made.
 */
export function TriggerDialog({
  columns,
  workflows,
  trigger,
  busy,
  onOpenChange,
  onSubmit,
}: TriggerDialogProps) {
  const t = useTranslations("pages.tables.triggers");
  const live = columns.filter((column) => !column.archived);
  const published = workflows.filter(
    (workflow) => workflow.current_version_id !== null && workflow.status !== "archived",
  );
  const seeded = rowsOf(trigger);
  const [workflowId, setWorkflowId] = useState(trigger?.workflow_id ?? "");
  const [name, setName] = useState(trigger?.name ?? "");
  const [filters, setFilters] = useState<FilterRow[]>(seeded.filters);
  const [mapping, setMapping] = useState<MappingRow[]>(
    seeded.mapping.length > 0 ? seeded.mapping : [{ key: "record_id", source: RECORD_ID_SOURCE }],
  );
  const byId = new Map(live.map((column) => [column.id, column]));
  const complete =
    workflowId !== "" &&
    filters.every(
      (row) => row.column_id !== "" && (row.op === "is_null" || row.value.trim() !== ""),
    ) &&
    mapping.every((row) => row.key.trim() !== "" && row.source !== "");

  const patchFilter = (index: number, change: Partial<FilterRow>) =>
    setFilters((rows) => rows.map((row, at) => (at === index ? { ...row, ...change } : row)));
  const patchMapping = (index: number, change: Partial<MappingRow>) =>
    setMapping((rows) => rows.map((row, at) => (at === index ? { ...row, ...change } : row)));

  function submit() {
    onSubmit({
      workflow_id: workflowId,
      name: name.trim() || null,
      filters: filters.map((row) => ({
        column_id: row.column_id,
        op: row.op,
        value: operand(byId.get(row.column_id), row.op, row.value),
      })),
      input_mapping: Object.fromEntries(mapping.map((row) => [row.key.trim(), row.source])),
    });
  }

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{trigger ? t("editTitle") : t("newTitle")}</DialogTitle>
          <DialogDescription>{t("dialogDescription")}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] space-y-5 overflow-y-auto pr-1">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="trigger-workflow">{t("workflow")}</Label>
              <Select
                value={workflowId}
                onValueChange={setWorkflowId}
                disabled={trigger !== undefined}
              >
                <SelectTrigger id="trigger-workflow">
                  <SelectValue placeholder={t("workflowPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {published.map((workflow) => (
                    <SelectItem key={workflow.id} value={workflow.id}>
                      {workflow.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {published.length === 0 && (
                <p className="text-muted-foreground text-xs">{t("noPublishedWorkflows")}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="trigger-name">{t("name")}</Label>
              <Input
                id="trigger-name"
                value={name}
                maxLength={120}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
          </div>

          <section className="space-y-2">
            <div>
              <h3 className="text-sm font-medium">{t("filtersTitle")}</h3>
              <p className="text-muted-foreground text-xs">{t("filtersHint")}</p>
            </div>
            {filters.map((row, index) => (
              <div key={index} className="grid grid-cols-[1fr_9rem_1fr_auto] items-center gap-2">
                <Select
                  value={row.column_id}
                  onValueChange={(value) => patchFilter(index, { column_id: value })}
                >
                  <SelectTrigger aria-label={t("filterColumn", { index: index + 1 })}>
                    <SelectValue placeholder={t("column")} />
                  </SelectTrigger>
                  <SelectContent>
                    {live.map((column) => (
                      <SelectItem key={column.id} value={column.id}>
                        {column.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select
                  value={row.op}
                  onValueChange={(value) => patchFilter(index, { op: value as FilterOp })}
                >
                  <SelectTrigger aria-label={t("filterOp", { index: index + 1 })}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {OPS.map((op) => (
                      <SelectItem key={op} value={op}>
                        {t(`ops.${op}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input
                  aria-label={t("filterValue", { index: index + 1 })}
                  value={row.value}
                  disabled={row.op === "is_null"}
                  onChange={(event) => patchFilter(index, { value: event.target.value })}
                />
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("removeFilter", { index: index + 1 })}
                  onClick={() => setFilters((rows) => rows.filter((_row, at) => at !== index))}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button
              variant="outline"
              size="sm"
              disabled={live.length === 0}
              onClick={() =>
                setFilters((rows) => [
                  ...rows,
                  { column_id: live[0]?.id ?? "", op: "eq", value: "" },
                ])
              }
            >
              <Plus className="h-4 w-4" />
              {t("addFilter")}
            </Button>
          </section>

          <section className="space-y-2">
            <div>
              <h3 className="text-sm font-medium">{t("mappingTitle")}</h3>
              <p className="text-muted-foreground text-xs">{t("mappingHint")}</p>
            </div>
            {mapping.map((row, index) => (
              <div key={index} className="grid grid-cols-[1fr_1fr_auto] items-center gap-2">
                <Input
                  aria-label={t("mappingKey", { index: index + 1 })}
                  className="font-mono text-xs"
                  value={row.key}
                  onChange={(event) => patchMapping(index, { key: event.target.value })}
                />
                <Select
                  value={row.source}
                  onValueChange={(value) => patchMapping(index, { source: value })}
                >
                  <SelectTrigger aria-label={t("mappingSource", { index: index + 1 })}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={RECORD_ID_SOURCE}>{t("recordId")}</SelectItem>
                    <SelectItem value={AUTHOR_SOURCE}>{t("author")}</SelectItem>
                    {live.map((column) => (
                      <SelectItem key={column.id} value={column.id}>
                        {column.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("removeMapping", { index: index + 1 })}
                  onClick={() => setMapping((rows) => rows.filter((_row, at) => at !== index))}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setMapping((rows) => [...rows, { key: "", source: AUTHOR_SOURCE }])}
            >
              <Plus className="h-4 w-4" />
              {t("addMapping")}
            </Button>
          </section>
          <p className="text-muted-foreground text-xs">{t("principalNote")}</p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={!complete || busy} onClick={submit}>
            {trigger ? t("save") : t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
