"use client";

import {
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useState } from "react";

/**
 * The picker's options: the shelves this organization already uses first -
 * the answer is usually "the same shelf as last time" - then the deployment's
 * predefined names that nobody has used yet.
 */
export function categorySuggestions(inUse: string[], suggested: string[]): string[] {
  return [...new Set([...inUse, ...suggested])];
}

/**
 * A category as the reader sees it, everywhere one is shown.
 *
 * The stored value is a slug - `customer-support`, `qa` - because that is what
 * two skills have to match on for the filter to see one shelf. But a slug is a
 * key, not a label: rendered raw it reads as a leak from the database. Spaces
 * for the hyphens, a capital to open, and a word too short to be a word is an
 * initialism - `qa` is QA, `hr` is HR.
 *
 * Display only. What is typed, sent and compared stays the slug, so
 * capitalizing a label can never split a shelf in two.
 */
export function categoryLabel(category: string): string {
  const words = category
    .trim()
    .split(/[-_\s]+/)
    .filter(Boolean);
  return words
    .map((word, index) => {
      if (word.length <= 2) return word.toUpperCase();
      return index === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word;
    })
    .join(" ");
}

/**
 * A Radix item cannot carry the empty string, so the two non-category rows
 * ride on sentinels no real shelf name will collide with.
 */
const NONE = "__no-category__";
const NEW = "__new-category__";

interface CategoryInputProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  suggestions: readonly string[];
  maxLength?: number;
  readOnly?: boolean;
}

/**
 * A category field: a select over the known shelves, with a way out of them.
 *
 * A select rather than a bare input, because the shelves are known - the ones
 * this organization uses plus the deployment's predefined names - and a field
 * that hides them until somebody starts typing makes each writer guess at a
 * list that already exists. That guessing is how twenty skills end up on
 * nineteen spellings of one shelf.
 *
 * But a category is still the organization's word, not ours: "New category…"
 * swaps the select for a text field, and whatever is typed there becomes an
 * option like any other. The current value is always listed even when nothing
 * suggested it, so a skill on a hand-written shelf does not open on a lie.
 */
export function CategoryInput({
  id,
  value,
  onChange,
  suggestions,
  maxLength,
  readOnly,
}: CategoryInputProps) {
  const [naming, setNaming] = useState(false);

  if (readOnly) {
    // A viewer reads the label too - nothing is sent from here.
    return <Input id={id} value={value.trim() === "" ? "" : categoryLabel(value)} readOnly />;
  }

  if (naming) {
    return (
      <Input
        id={id}
        // Focused on mount: this field only appears because "New category…"
        // was just clicked, and the click's momentum belongs in it. Not the
        // autoFocus attribute - that one is for page load, and the a11y rule
        // rightly flags it.
        ref={(node) => node?.focus()}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="support"
        maxLength={maxLength}
        onBlur={() => setNaming(false)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === "Escape") setNaming(false);
        }}
      />
    );
  }

  const current = value.trim();
  const options = [...new Set([...(current === "" ? [] : [current]), ...suggestions])];

  return (
    <Select
      value={current === "" ? NONE : current}
      onValueChange={(picked) => {
        if (picked === NEW) {
          onChange("");
          setNaming(true);
          return;
        }
        onChange(picked === NONE ? "" : picked);
      }}
    >
      <SelectTrigger id={id}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>
          <span className="text-muted-foreground">No category</span>
        </SelectItem>
        {options.map((suggestion) => (
          <SelectItem key={suggestion} value={suggestion}>
            {categoryLabel(suggestion)}
          </SelectItem>
        ))}
        <SelectSeparator />
        <SelectItem value={NEW}>New category…</SelectItem>
      </SelectContent>
    </Select>
  );
}
