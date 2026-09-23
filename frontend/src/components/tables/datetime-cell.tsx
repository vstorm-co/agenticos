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
 *
 * The parent keeps this mounted across records - `record-detail-sheet.tsx`
 * keys its editors by column id, not by record id - so `local` has to be
 * re-seeded whenever `value` changes for a reason other than this cell's own
 * `onBlur` (switching the open record, "reload and reapply", "discard").
 * Re-seeding on every render would fight the in-progress typing this
 * component exists to hold; re-seeding only when `value` has actually moved
 * since the render that last saw it - the same render-time pattern
 * `schema-editor-dialog.tsx` and `use-url-state.ts` use - does neither.
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
  const [seenValue, setSeenValue] = useState(value);
  const [local, setLocal] = useState(() => toLocalInputValue(value));
  if (value !== seenValue) {
    setSeenValue(value);
    setLocal(toLocalInputValue(value));
  }

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
