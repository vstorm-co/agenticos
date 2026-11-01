"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ArrowDown, ArrowUp, GripVertical, Settings2 } from "lucide-react";
import {
  Button,
  Checkbox,
  Label,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { formatCellValue } from "@/lib/format-cell-value";
import { orderedTableColumns, viewColumnKey } from "@/lib/table-display";
import { TABLE_SYSTEM_COLUMNS } from "@/lib/table-system-columns";
import { cn } from "@/lib/utils";
import type { ColumnDef, TableDisplay } from "@/types/tables";

const DATE_FORMATS = ["locale", "iso", "day_first", "month_first", "long"] as const;
const TIME_FORMATS = ["locale", "24h", "12h", "hidden"] as const;

/** One view's presentation; no schema or record writes happen here. */
export function ViewSettingsPopover({
  columns,
  visible,
  display,
  onChange,
  onToggle,
}: {
  columns: ColumnDef[];
  visible: string[] | null;
  display: TableDisplay;
  onChange: (next: TableDisplay) => void;
  onToggle: (column: ColumnDef, shown: boolean) => void;
}) {
  const t = useTranslations("tables.viewSettings");
  const tm = useTranslations("tables.markdown");
  const locale = useLocale();
  const [dragged, setDragged] = useState<string | null>(null);
  const [target, setTarget] = useState<string | null>(null);
  const ordered = orderedTableColumns(columns, display.column_order);
  const label = (column: ColumnDef) =>
    column.system
      ? tm(
          {
            created_at: "createdAt",
            updated_at: "updatedAt",
            created_by: "createdBy",
            updated_by: "updatedBy",
          }[column.system],
        )
      : column.label;
  const shown = (column: ColumnDef) =>
    column.system
      ? !display.hidden_system_columns.includes(column.system)
      : visible === null || visible.includes(column.id);
  const move = (key: string, index: number) => {
    const order = ordered.map(viewColumnKey);
    const from = order.indexOf(key);
    if (from < 0 || index < 0 || index >= order.length || from === index) return;
    order.splice(from, 1);
    order.splice(index, 0, key);
    onChange({ ...display, column_order: order });
  };
  const sample = TABLE_SYSTEM_COLUMNS[0];
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2" data-tour="table-view-settings">
          <Settings2 className="size-4" />
          {t("title")}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="flex max-h-[var(--radix-popover-content-available-height)] w-96 max-w-[calc(100vw-2rem)] flex-col p-0"
      >
        <div className="border-border shrink-0 border-b p-4">
          <h3 className="text-sm font-semibold">{t("title")}</h3>
          <p className="text-muted-foreground mt-1 text-xs">{t("description")}</p>
        </div>
        <div className="max-h-[65dvh] min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
          <section className="space-y-2" aria-label={t("columns")}>
            <div className="flex items-center justify-between gap-2">
              <h4 className="text-xs font-medium">{t("columns")}</h4>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-xs"
                onClick={() => {
                  onChange({ ...display, column_order: [] });
                }}
              >
                {t("resetOrder")}
              </Button>
            </div>
            <p className="text-muted-foreground text-xs">{t("reorderHint")}</p>
            <div className="space-y-1">
              {ordered.map((column, index) => {
                const key = viewColumnKey(column);
                const name = label(column);
                return (
                  <div
                    key={key}
                    role="presentation"
                    data-view-column={key}
                    draggable
                    onDragStart={(event) => {
                      setDragged(key);
                      event.dataTransfer.effectAllowed = "move";
                      event.dataTransfer.setData("text/plain", key);
                    }}
                    className={cn(
                      "flex items-center gap-2 rounded-md border border-transparent px-1 py-1",
                      target === key && "border-ring bg-accent",
                      dragged === key && "opacity-50",
                    )}
                    onDragOver={(event) => {
                      if (dragged !== null) {
                        event.preventDefault();
                        setTarget(key);
                      }
                    }}
                    onDrop={(event) => {
                      event.preventDefault();
                      if (dragged !== null) move(dragged, index);
                      setDragged(null);
                      setTarget(null);
                    }}
                    onDragEnd={() => {
                      setDragged(null);
                      setTarget(null);
                    }}
                  >
                    <button
                      type="button"
                      draggable
                      className="text-muted-foreground cursor-grab active:cursor-grabbing"
                      aria-label={t("drag", { column: name })}
                    >
                      <GripVertical className="size-4" />
                    </button>
                    <Checkbox
                      id={`view-column-${key}`}
                      checked={shown(column)}
                      onCheckedChange={(checked) => onToggle(column, checked === true)}
                      aria-label={t("showColumn", { column: name })}
                    />
                    <Label
                      htmlFor={`view-column-${key}`}
                      className="min-w-0 flex-1 truncate text-xs"
                    >
                      {name}
                    </Label>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-6 shrink-0"
                      disabled={index === 0}
                      aria-label={t("moveUp", { column: name })}
                      onClick={() => move(key, index - 1)}
                    >
                      <ArrowUp className="size-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-6 shrink-0"
                      disabled={index === ordered.length - 1}
                      aria-label={t("moveDown", { column: name })}
                      onClick={() => move(key, index + 1)}
                    >
                      <ArrowDown className="size-3.5" />
                    </Button>
                  </div>
                );
              })}
            </div>
          </section>
          <section className="border-border space-y-4 border-t pt-4" aria-label={t("appearance")}>
            <h4 className="text-xs font-medium">{t("appearance")}</h4>
            <div className="flex items-center justify-between gap-3">
              <Label htmlFor="view-wrap-text" className="text-sm">
                {t("wrapText")}
              </Label>
              <Switch
                id="view-wrap-text"
                checked={display.wrap_text}
                onCheckedChange={(wrap_text) => onChange({ ...display, wrap_text })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="view-date-format">{t("dateFormat")}</Label>
              <Select
                value={display.date_format}
                onValueChange={(value) => {
                  const date_format = DATE_FORMATS.find((format) => format === value);
                  if (date_format) onChange({ ...display, date_format });
                }}
              >
                <SelectTrigger id="view-date-format">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DATE_FORMATS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {t(`date.${value}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="view-time-format">{t("timeFormat")}</Label>
              <Select
                value={display.time_format}
                onValueChange={(value) => {
                  const time_format = TIME_FORMATS.find((format) => format === value);
                  if (time_format) onChange({ ...display, time_format });
                }}
              >
                <SelectTrigger id="view-time-format">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TIME_FORMATS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {t(`time.${value}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {sample && (
              <p className="bg-muted text-muted-foreground rounded-md px-3 py-2 text-xs">
                {t("preview")}:{" "}
                {formatCellValue(sample, "2026-10-31T16:05:00", String, locale, display)}
              </p>
            )}
          </section>
        </div>
      </PopoverContent>
    </Popover>
  );
}
