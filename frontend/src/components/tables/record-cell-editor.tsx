"use client";

import { useTranslations } from "next-intl";
import {
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Textarea,
} from "@/components/ui";
import { DateCell } from "./date-cell";
import { DatetimeCell } from "./datetime-cell";
import { MultiSelectCell } from "./multi-select-cell";
import type { CellValue, ColumnDef } from "@/types/tables";

const UNSET = "__unset__";

/**
 * One column's control, dispatched on `ColumnDef.type`.
 *
 * The shape `schema-form.tsx` uses - controlled `value`/`onChange`, `disabled`,
 * an `error` shown beside the control - but as a single field rather than a
 * whole generated form: a table cell is edited one at a time, inline in a grid
 * or N times inside `record-detail-sheet.tsx`, not as one form that opens every
 * column at once. `undefined` means untouched (the record's own stored value
 * is shown); `null` means explicitly cleared.
 */
export function RecordCellEditor({
  column,
  value,
  onChange,
  disabled,
  error,
}: {
  column: ColumnDef;
  value: CellValue;
  onChange: (value: CellValue) => void;
  disabled?: boolean;
  error?: string;
}) {
  const t = useTranslations("tables.cells");
  const id = `cell-${column.id}`;
  const errorId = `${id}-error`;
  const invalid =
    error === undefined ? {} : { "aria-invalid": true as const, "aria-describedby": errorId };

  return (
    <div className="space-y-1.5">
      {column.type === "text" && (
        <Input
          id={id}
          value={typeof value === "string" ? value : ""}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          {...invalid}
        />
      )}

      {column.type === "long_text" && (
        <Textarea
          id={id}
          value={typeof value === "string" ? value : ""}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          {...invalid}
        />
      )}

      {column.type === "number" && (
        <Input
          id={id}
          type="number"
          step="any"
          value={typeof value === "number" ? value : ""}
          disabled={disabled}
          onChange={(event) =>
            onChange(event.target.value === "" ? null : Number(event.target.value))
          }
          {...invalid}
        />
      )}

      {column.type === "integer" && (
        <Input
          id={id}
          type="number"
          step="1"
          value={typeof value === "number" ? value : ""}
          disabled={disabled}
          onChange={(event) => {
            const raw = event.target.value;
            onChange(raw === "" ? null : Math.trunc(Number(raw)));
          }}
          {...invalid}
        />
      )}

      {column.type === "boolean" &&
        (column.nullable ? (
          <Select
            value={value === true ? "true" : value === false ? "false" : UNSET}
            disabled={disabled}
            onValueChange={(next) => onChange(next === UNSET ? null : next === "true")}
          >
            <SelectTrigger id={id}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={UNSET}>{t("notSet")}</SelectItem>
              <SelectItem value="true">{t("true")}</SelectItem>
              <SelectItem value="false">{t("false")}</SelectItem>
            </SelectContent>
          </Select>
        ) : (
          <Switch
            id={id}
            checked={value === true}
            onCheckedChange={onChange}
            disabled={disabled}
            {...invalid}
          />
        ))}

      {column.type === "date" && (
        <DateCell
          id={id}
          value={typeof value === "string" ? value : null}
          onChange={onChange}
          disabled={disabled}
          {...invalid}
        />
      )}

      {column.type === "datetime" && (
        <DatetimeCell
          id={id}
          value={typeof value === "string" ? value : null}
          onChange={onChange}
          disabled={disabled}
          {...invalid}
        />
      )}

      {column.type === "single_select" && (
        <Select
          value={typeof value === "string" ? value : UNSET}
          disabled={disabled}
          onValueChange={(next) => onChange(next === UNSET ? null : next)}
        >
          <SelectTrigger id={id}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={UNSET}>{t("notSet")}</SelectItem>
            {column.options
              .filter((option) => !option.archived || option.id === value)
              .map((option) => (
                <SelectItem key={option.id} value={option.id}>
                  {option.archived ? (
                    <span className="line-through">{option.label}</span>
                  ) : (
                    option.label
                  )}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      )}

      {column.type === "multi_select" && (
        <MultiSelectCell
          id={id}
          options={column.options}
          value={Array.isArray(value) ? value : []}
          onChange={onChange}
          disabled={disabled}
        />
      )}

      {error !== undefined && (
        <p id={errorId} className="text-destructive text-xs">
          {error}
        </p>
      )}
    </div>
  );
}
