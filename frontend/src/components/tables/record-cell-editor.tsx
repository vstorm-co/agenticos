"use client";

import { useState } from "react";
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
 * A local, re-seeded text buffer - the same render-time pattern
 * `DatetimeCell` uses, generalized to any control whose native `onChange`
 * fires once per keystroke. Committing straight to the caller's `onChange`
 * there means every keystroke in a detail sheet or grid cell fires a PATCH,
 * racing later keystrokes against earlier ones and against a concurrent
 * editor's own writes; buffering locally and committing on blur makes one
 * PATCH per edit, the same as every other control here (a `Select`, a
 * `Switch`, `DateCell`, `DatetimeCell` all commit once per discrete choice).
 */
function useTextBuffer(value: string, onCommit: (raw: string) => void) {
  const [seen, setSeen] = useState(value);
  const [draft, setDraft] = useState(value);
  if (value !== seen) {
    setSeen(value);
    setDraft(value);
  }
  return {
    draft,
    onChange: setDraft,
    onBlur: () => {
      if (draft !== seen) onCommit(draft);
    },
  };
}

function TextCellInput({
  id,
  value,
  onChange,
  disabled,
  ...invalid
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
} & Record<string, unknown>) {
  const buffer = useTextBuffer(value, onChange);
  return (
    <Input
      id={id}
      value={buffer.draft}
      disabled={disabled}
      onChange={(event) => buffer.onChange(event.target.value)}
      onBlur={buffer.onBlur}
      {...invalid}
    />
  );
}

function LongTextCellInput({
  id,
  value,
  onChange,
  disabled,
  ...invalid
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
} & Record<string, unknown>) {
  const buffer = useTextBuffer(value, onChange);
  return (
    <Textarea
      id={id}
      value={buffer.draft}
      disabled={disabled}
      onChange={(event) => buffer.onChange(event.target.value)}
      onBlur={buffer.onBlur}
      {...invalid}
    />
  );
}

function NumberCellInput({
  id,
  value,
  onChange,
  disabled,
  truncate,
  ...invalid
}: {
  id: string;
  value: number | null;
  onChange: (value: number | null) => void;
  disabled?: boolean;
  truncate?: boolean;
} & Record<string, unknown>) {
  const stored = typeof value === "number" ? String(value) : "";
  const buffer = useTextBuffer(stored, (raw) => {
    if (raw === "") {
      onChange(null);
      return;
    }
    onChange(truncate ? Math.trunc(Number(raw)) : Number(raw));
  });
  return (
    <Input
      id={id}
      type="number"
      step={truncate ? "1" : "any"}
      value={buffer.draft}
      disabled={disabled}
      onChange={(event) => buffer.onChange(event.target.value)}
      onBlur={buffer.onBlur}
      {...invalid}
    />
  );
}

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
        <TextCellInput
          id={id}
          value={typeof value === "string" ? value : ""}
          onChange={onChange}
          disabled={disabled}
          {...invalid}
        />
      )}

      {column.type === "long_text" && (
        <LongTextCellInput
          id={id}
          value={typeof value === "string" ? value : ""}
          onChange={onChange}
          disabled={disabled}
          {...invalid}
        />
      )}

      {column.type === "number" && (
        <NumberCellInput
          id={id}
          value={typeof value === "number" ? value : null}
          onChange={onChange}
          disabled={disabled}
          {...invalid}
        />
      )}

      {column.type === "integer" && (
        <NumberCellInput
          id={id}
          value={typeof value === "number" ? value : null}
          onChange={onChange}
          disabled={disabled}
          truncate
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
