"use client";

import { useLayoutEffect, useRef } from "react";
import { useTranslations } from "next-intl";

import { Label, Textarea } from "@/components/ui";
import type { ColumnDef } from "@/types/tables";

/** What a formula may read: a live column holding values, not another formula or a link. */
function readable(column: ColumnDef): boolean {
  return !column.archived && column.type !== "formula" && column.type !== "link";
}

/**
 * A formula column's expression: typed, with the table's columns offered as
 * chips that write `{Label}` where the cursor is, and the functions it may call
 * named underneath. The service checks it on save and names what is wrong.
 */
export function FormulaField({
  id,
  value,
  columns,
  onChange,
  error,
}: {
  id: string;
  value: string;
  columns: ColumnDef[];
  onChange: (value: string) => void;
  error?: string;
}) {
  const t = useTranslations("tables.formula");
  const field = useRef<HTMLTextAreaElement>(null);
  // Where the cursor goes once an inserted reference is in the field: after the
  // render that puts it there, or React's own value update would move it back.
  const cursor = useRef<number | null>(null);

  useLayoutEffect(() => {
    const at = cursor.current;
    if (at === null) return;
    cursor.current = null;
    field.current?.focus();
    field.current?.setSelectionRange(at, at);
  }, [value]);

  const insert = (label: string) => {
    const reference = `{${label}}`;
    const start = field.current?.selectionStart ?? value.length;
    const end = field.current?.selectionEnd ?? value.length;
    cursor.current = start + reference.length;
    onChange(value.slice(0, start) + reference + value.slice(end));
  };

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{t("label")}</Label>
      <Textarea
        ref={field}
        id={id}
        value={value}
        rows={3}
        maxLength={1000}
        className="font-mono text-xs"
        placeholder={t("placeholder")}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error === undefined ? undefined : true}
      />
      <div className="flex flex-wrap gap-1" aria-label={t("columns")}>
        {columns.filter(readable).map((column) => (
          <button
            key={column.id}
            type="button"
            onClick={() => insert(column.label)}
            className="bg-secondary text-secondary-foreground hover:bg-secondary/70 focus-visible:ring-ring rounded-md px-2 py-0.5 text-xs focus-visible:ring-1 focus-visible:outline-none"
          >
            {column.label}
          </button>
        ))}
      </div>
      <p className="text-muted-foreground text-xs">{t("hint")}</p>
      {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}
