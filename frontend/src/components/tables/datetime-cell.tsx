"use client";

import { useState } from "react";
import { Input } from "@/components/ui";

/** `YYYY-MM-DDTHH:mm` in the browser's own time zone, or `""` for no value. */
function toLocalInputValue(isoUtc: string | null): string {
  if (!isoUtc) return "";
  const date = new Date(isoUtc);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** The column's own wire format: ISO 8601 in UTC, or `null` for no value. */
function toUtcIso(local: string): string | null {
  if (!local) return null;
  const date = new Date(local);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/**
 * A single `datetime` cell.
 *
 * The one control here with a real extension beyond the native input: it holds
 * the browser's local wall-clock string while the field is being typed into,
 * and converts it to the column's UTC ISO 8601 only on blur - converting on
 * every keystroke would fight the native `datetime-local` widget's own segment
 * navigation.
 */
export function DatetimeCell({
  id,
  value,
  onChange,
  disabled,
  ...invalid
}: {
  id?: string;
  value: string | null;
  onChange: (value: string | null) => void;
  disabled?: boolean;
} & Record<string, unknown>) {
  const [local, setLocal] = useState(() => toLocalInputValue(value));

  return (
    <Input
      id={id}
      type="datetime-local"
      value={local}
      disabled={disabled}
      onChange={(event) => setLocal(event.target.value)}
      onBlur={() => onChange(toUtcIso(local))}
      {...invalid}
    />
  );
}
