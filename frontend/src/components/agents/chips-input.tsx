"use client";

import { useState } from "react";
import { Plus, X } from "lucide-react";

import { Badge, Input } from "@/components/ui";
import { cn } from "@/lib/utils";

/**
 * Truncate to `limit` Unicode code points, not UTF-16 code units.
 *
 * The native `maxLength` attribute counts UTF-16 units, but the backend's
 * `len(label)` and the `varchar(32)` column both count code points - so a
 * label of 17-32 supplementary characters (an emoji, for instance) is valid to
 * store but `maxLength` would cut it off at 16. `Array.from` splits on code
 * points, matching Python's `len()` on the same string.
 */
function clampToCodePoints(value: string, limit: number): string {
  const codePoints = Array.from(value);
  return codePoints.length > limit ? codePoints.slice(0, limit).join("") : value;
}

/**
 * A chips editor: type a value, commit it as a removable chip.
 *
 * Commit on Enter and on blur; remove the last chip with Backspace on an empty
 * box, or any chip with its ✕. `maxItems` is an affordance, not the rule - the
 * box is disabled once the list is full and the server is the real backstop, so
 * the count and the per-item length are only ever hints here. A duplicate is
 * dropped on the client too, but the canonical fold is the server's.
 *
 * `suggestions` are the labels already in use, offered under the box while it
 * has focus and narrowed by what is typed - so a second agent lands in
 * "Support" rather than beside it in "support" or "Customer support".
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
  suggestions = [],
  suggestionsLabel,
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
  suggestions?: string[];
  /** Accessible name for the group of suggestions; required when there are any. */
  suggestionsLabel?: string;
}) {
  const [draft, setDraft] = useState("");
  const [focused, setFocused] = useState(false);
  const full = values.length >= maxItems;
  const needle = draft.trim().toLowerCase();
  const offered = suggestions
    .filter((label) => !values.includes(label) && label.toLowerCase().includes(needle))
    .slice(0, MAX_SUGGESTIONS);

  const add = (value: string) => {
    if (!values.includes(value)) onChange([...values, value]);
  };

  const commit = () => {
    const value = draft.trim();
    setDraft("");
    if (!value) return;
    // A label typed in another case is the one already in use, not a new one.
    add(suggestions.find((label) => label.toLowerCase() === value.toLowerCase()) ?? value);
  };

  const removeAt = (value: string) => onChange(values.filter((item) => item !== value));

  return (
    <div className="space-y-2">
      <div
        className={cn(
          // The height and edge of every other field: a 36px row with the same
          // 1.5px border, ringed when anything inside it has focus.
          "border-input focus-within:ring-ring flex min-h-9 flex-wrap items-center gap-1.5 rounded-lg border-[1.5px] px-1.5 py-0.5 focus-within:ring-1",
          disabled && "opacity-50",
        )}
      >
        {values.map((value) => (
          <Badge key={value} variant="secondary" className="gap-1 font-normal">
            {value}
            <button
              type="button"
              aria-label={removeLabel(value)}
              // Keep focus on the input: a mousedown that blurred it would commit the
              // in-progress draft as a chip before this click removes the intended one.
              onMouseDown={(event) => event.preventDefault()}
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
          disabled={disabled || full}
          onChange={(event) => setDraft(clampToCodePoints(event.target.value, maxLength))}
          onFocus={() => setFocused(true)}
          onBlur={() => {
            setFocused(false);
            commit();
          }}
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
      {focused && !full && offered.length > 0 && (
        <div role="group" aria-label={suggestionsLabel} className="flex flex-wrap gap-1.5">
          {offered.map((label) => (
            <button
              key={label}
              type="button"
              // Keep focus in the box, as the chips' own remove buttons do: a blur
              // would commit the half-typed draft and hide this row mid-click.
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                setDraft("");
                add(label);
              }}
              className="border-input text-muted-foreground hover:text-foreground hover:bg-accent inline-flex h-6 items-center gap-1 rounded-full border border-dashed px-2 text-xs transition-colors"
            >
              <Plus className="size-3" aria-hidden />
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Enough to choose from at a glance; typing narrows the rest. */
const MAX_SUGGESTIONS = 8;
