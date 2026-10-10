"use client";

import { ChevronDown, ListFilter } from "lucide-react";

import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";

/**
 * A multi-select over one discovery facet - the agents catalog's categories or
 * tags - drawn as the skills page draws its category filter.
 *
 * The choices are the server's (every label on an agent the caller may list),
 * so a filter is picked rather than guessed at. A selected value the choices no
 * longer carry - its last agent was archived out of the listing - stays in the
 * menu, checked, so it can still be unpicked.
 *
 * `max` is how many the API honours. Past it the server keeps the first and
 * drops the rest silently, so once it is reached the unchecked choices are
 * disabled rather than offered as picks that would change nothing (#1930).
 */
export function LabelFilter({
  options,
  selected,
  onChange,
  ariaLabel,
  allLabel,
  countLabel,
  clearLabel,
  max,
}: {
  options: string[];
  selected: string[];
  onChange: (next: string[]) => void;
  ariaLabel: string;
  allLabel: string;
  countLabel: (count: number) => string;
  clearLabel: string;
  max: number;
}) {
  const choices = [...new Set([...options, ...selected])].sort();
  if (choices.length === 0) return null;
  const full = selected.length >= max;

  const toggle = (value: string) =>
    onChange(
      selected.includes(value) ? selected.filter((entry) => entry !== value) : [...selected, value],
    );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" aria-label={ariaLabel}>
          <ListFilter className="h-4 w-4" />
          {selected.length === 0
            ? allLabel
            : selected.length === 1
              ? selected[0]
              : countLabel(selected.length)}
          <ChevronDown className="h-4 w-4 opacity-60" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-72 overflow-y-auto">
        {choices.map((value) => (
          <DropdownMenuCheckboxItem
            key={value}
            checked={selected.includes(value)}
            disabled={full && !selected.includes(value)}
            onCheckedChange={() => toggle(value)}
            // Picking several is the point; the menu staying open is what
            // makes it a multi-select rather than a detour.
            onSelect={(event) => event.preventDefault()}
          >
            {value}
          </DropdownMenuCheckboxItem>
        ))}
        {selected.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => onChange([])}>{clearLabel}</DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
