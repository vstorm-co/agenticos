"use client";

import { COMMAND_ITEM_FOCUS } from "@/components/ui/control-styles";

import { useState } from "react";
import { Command } from "cmdk";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { GroupIcon } from "@/components/groups/group-icon";
import { MemberIdentity, displayName } from "@/components/orgs/member-identity";
import { Button, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { Group } from "@/types/groups";
import type { OrganizationMember } from "@/types";
import { encodeSubject } from "./grants";

/** Reserve the search header before using the popover’s remaining collision space. */
const SUBJECT_LIST_HEIGHT =
  "max-h-[min(26rem,calc(var(--radix-popover-content-available-height,60dvh)-3.5rem))]";

const HEADINGS =
  "[&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:uppercase";

const ROW = cn(
  COMMAND_ITEM_FOCUS,
  "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm",
);

interface SubjectPickerProps {
  id: string;
  members: OrganizationMember[];
  groups: Group[];
  /** The chosen subject, encoded; empty for none. */
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  disabled?: boolean;
}

/**
 * One member or group to share with, found by typing part of a name or an
 * address.
 *
 * The shape `MemberPicker` takes, and for its reason: a search field inside a
 * Radix select fights the select's own typeahead. A plain select listed the whole
 * organization with no way to type, which past a handful of people is a scroll
 * through every address to find one.
 */
export function SubjectPicker({
  id,
  members,
  groups,
  value,
  onChange,
  placeholder,
  disabled,
}: SubjectPickerProps) {
  const t = useTranslations("sharing");
  const tOrgs = useTranslations("orgs");
  const [open, setOpen] = useState(false);

  const chosenMember = members.find(
    (member) => encodeSubject({ kind: "user", id: member.user_id }) === value,
  );
  const chosenGroup = groups.find(
    (group) => encodeSubject({ kind: "group", id: group.id }) === value,
  );
  const chosen = chosenMember ? displayName(chosenMember) : chosenGroup?.name;

  function pick(subject: string) {
    onChange(subject);
    setOpen(false);
  }

  return (
    // A portaled picker inside a modal needs its own scroll-lock scope, or the outer lock cancels its wheel/touch events.
    <Popover modal open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className="w-full justify-between font-normal"
        >
          <span className={cn("truncate", chosen === undefined && "text-muted-foreground")}>
            {chosen ?? placeholder}
          </span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60" />
        </Button>
      </PopoverTrigger>

      <PopoverContent
        className="flex min-h-0 w-[min(22rem,90vw)] flex-col overflow-hidden rounded-lg p-0"
        align="start"
      >
        <Command shouldFilter className={cn(HEADINGS, "flex min-h-0 flex-col")}>
          <div className="border-border shrink-0 border-b px-3 py-2">
            <Command.Input
              placeholder={t("searchSubjects")}
              aria-label={t("searchSubjects")}
              className="placeholder:text-muted-foreground w-full bg-transparent text-sm outline-none"
            />
          </div>

          <Command.List
            className={cn(
              SUBJECT_LIST_HEIGHT,
              "min-h-0 scrollbar-thin overflow-y-auto overscroll-contain p-1",
            )}
          >
            <Command.Empty className="text-muted-foreground px-3 py-6 text-center text-sm">
              {tOrgs("nobodyHereMatches")}
            </Command.Empty>

            {groups.length > 0 && (
              <Command.Group heading={t("groupsHeading")}>
                {groups.map((group) => (
                  <Command.Item
                    key={group.id}
                    value={group.name}
                    aria-label={group.name}
                    onSelect={() => pick(encodeSubject({ kind: "group", id: group.id }))}
                    className={ROW}
                  >
                    <GroupIcon
                      icon={group.icon}
                      className="size-5 shrink-0 rounded-full [&_svg]:size-3"
                    />
                    <span className="truncate">{group.name}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            {members.length > 0 && (
              <Command.Group heading={t("membersHeading")}>
                {members.map((member) => (
                  <Command.Item
                    key={member.user_id}
                    // cmdk filters on this string, never on what the row draws, so
                    // it holds the name and the address both - and the address
                    // keeps two namesakes apart.
                    value={`${displayName(member)} ${member.email}`}
                    aria-label={
                      member.full_name ? `${member.full_name} (${member.email})` : member.email
                    }
                    onSelect={() => pick(encodeSubject({ kind: "user", id: member.user_id }))}
                    className={ROW}
                  >
                    <MemberIdentity member={member} className="min-w-0 flex-1" />
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </Command.List>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
