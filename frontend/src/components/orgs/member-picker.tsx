"use client";

import { useState } from "react";
import { Command } from "cmdk";
import { Check, ChevronDown, UserPlus } from "lucide-react";

import { MemberIdentity, displayName } from "./member-identity";
import type { IdentifiedMember } from "./member-identity";
import { Button, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { cn } from "@/lib/utils";

interface MemberPickerProps {
  members: IdentifiedMember[];
  /** The chosen ids, in the order they were chosen. */
  selected: string[];
  onToggle: (userId: string) => void;
  /** What the trigger says, given how many are chosen. */
  label: (count: number) => string;
  /** Prefixes every option's accessible name, so two pickers on one page differ. */
  scope: string;
  disabled?: boolean;
}

/** Ten rows of a two-line person, and then a scrollbar. */
const TEN_ROWS = "max-h-[min(26rem,60vh)]";

/**
 * Choosing people out of an organization.
 *
 * A `Popover` and a `cmdk` list rather than a menu, which is the shape the model
 * picker already uses — and not only for consistency. A search field inside a
 * `DropdownMenu` fights the menu's own typeahead: Radix reads keystrokes to jump
 * between items, so typing "bo" moves focus instead of filtering. `Command` is built
 * for a list that is searched.
 *
 * Bounded at ten rows because an organization is not a handful: forty members in a
 * panel with no ceiling is a page that scrolls past its own controls, and forty as
 * pills — which this replaced — was worse.
 *
 * Each row is the person as the rest of the application draws one, a face and a name
 * over the address. A bare first name is not something two colleagues called Bob can
 * be told apart by, and the address is the thing that is unique.
 */
export function MemberPicker({
  members,
  selected,
  onToggle,
  label,
  scope,
  disabled,
}: MemberPickerProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" disabled={disabled}>
          <UserPlus className="h-3.5 w-3.5" />
          {label(selected.length)}
          <ChevronDown className="h-3.5 w-3.5 opacity-60" />
        </Button>
      </PopoverTrigger>

      {/* `rounded-lg`, not the popover's own `rounded-xl`: that radius is for a card
          with padding, and on a flush list it curves away from the first and last
          rows. `p-0` for the same reason - the list brings its own. */}
      <PopoverContent className="w-[min(22rem,90vw)] rounded-lg p-0" align="start">
        <Command shouldFilter>
          <div className="border-border border-b px-3 py-2">
            {/* No `autoFocus`: Radix moves focus into the panel when it opens, and
                the search field is the first thing in it. */}
            <Command.Input
              value={search}
              onValueChange={setSearch}
              placeholder="Search people…"
              className="placeholder:text-muted-foreground w-full bg-transparent text-sm outline-none"
            />
          </div>

          <Command.List className={cn(TEN_ROWS, "overflow-y-auto p-1")}>
            <Command.Empty className="text-muted-foreground px-3 py-6 text-center text-sm">
              Nobody here matches that.
            </Command.Empty>

            {members.map((member) => {
              const chosen = selected.includes(member.user_id);
              return (
                <Command.Item
                  key={member.user_id}
                  // Both, so the search matches whichever one somebody types. cmdk
                  // filters on this string and never on what the row renders.
                  value={`${displayName(member)} ${member.email}`}
                  role="option"
                  aria-selected={chosen}
                  aria-label={`${scope}: ${displayName(member)} (${member.email})`}
                  onSelect={() => onToggle(member.user_id)}
                  className="aria-selected:bg-accent data-[selected=true]:bg-accent flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5"
                >
                  <MemberIdentity member={member} className="min-w-0 flex-1" />
                  <Check
                    className={cn("h-4 w-4 shrink-0", chosen ? "opacity-100" : "opacity-0")}
                    aria-hidden
                  />
                </Command.Item>
              );
            })}
          </Command.List>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
