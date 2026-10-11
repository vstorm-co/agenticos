"use client";

import { Input } from "@/components/ui";

/**
 * A single `date` cell: no existing primitive is a bare date (`date-range-picker.tsx`
 * is ranges only), so this is the native `<input type="date">`, which already
 * speaks `YYYY-MM-DD` - the column's own wire format.
 */
export function DateCell({
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
  return (
    <Input
      id={id}
      type="date"
      value={value ?? ""}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
      {...invalid}
    />
  );
}
