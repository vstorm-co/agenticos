"use client";

import { useState } from "react";
import { X } from "lucide-react";

import { Badge, Input } from "@/components/ui";
import { cn } from "@/lib/utils";

/**
 * A chips editor: type a value, commit it as a removable chip.
 *
 * Commit on Enter and on blur; remove the last chip with Backspace on an empty
 * box, or any chip with its ✕. `maxItems` is an affordance, not the rule - the
 * box is disabled once the list is full and the server is the real backstop, so
 * the count and the per-item length are only ever hints here. A duplicate is
 * dropped on the client too, but the canonical fold is the server's.
 */
export function ChipsInput({
  values,
  onChange,
  inputLabel,
  removeLabel,
  placeholder,
  maxItems,
  maxLength,
  disabled = false,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  /** Accessible name for the text box. */
  inputLabel: string;
  /** Accessible name for one chip's remove button, given the chip's value. */
  removeLabel: (value: string) => string;
  placeholder?: string;
  maxItems: number;
  maxLength: number;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const full = values.length >= maxItems;

  const commit = () => {
    const value = draft.trim();
    setDraft("");
    if (!value) return;
    if (!values.includes(value)) onChange([...values, value]);
  };

  const removeAt = (value: string) => onChange(values.filter((item) => item !== value));

  return (
    <div
      className={cn(
        "border-input flex flex-wrap items-center gap-1.5 rounded-lg border p-1.5",
        disabled && "opacity-50",
      )}
    >
      {values.map((value) => (
        <Badge key={value} variant="secondary" className="gap-1 font-normal">
          {value}
          <button
            type="button"
            aria-label={removeLabel(value)}
            onClick={() => removeAt(value)}
            disabled={disabled}
            className="hover:text-foreground text-muted-foreground rounded-full outline-none focus-visible:ring-2 disabled:cursor-not-allowed"
          >
            <X className="h-3 w-3" />
          </button>
        </Badge>
      ))}
      <Input
        aria-label={inputLabel}
        value={draft}
        placeholder={placeholder}
        maxLength={maxLength}
        disabled={disabled || full}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          } else if (event.key === "Backspace" && draft === "") {
            const last = values[values.length - 1];
            if (last !== undefined) removeAt(last);
          }
        }}
        className="h-7 w-32 flex-1 border-0 focus-visible:ring-0"
      />
    </div>
  );
}
