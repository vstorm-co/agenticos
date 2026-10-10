"use client";

import { useState } from "react";
import { Search, User, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { GroupIcon } from "@/components/groups/group-icon";
import { Input } from "@/components/ui";
import { useGroups, useMembers } from "@/hooks";
import { useOrgStore } from "@/stores";
import type { Audience } from "./audience-picker";

const SUGGESTIONS = 8;

/**
 * Find groups and people by typing, and keep each one picked as a chip (#2072).
 *
 * Groups are offered before anything is typed - an organization has a handful -
 * while people are found by name or address, since listing every member would
 * bury the departments the picker is mostly for.
 */
export function AudienceSearch({
  value,
  onChange,
  disabled,
}: {
  value: Audience;
  onChange: (audience: Audience) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("audience");
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const { groups } = useGroups(orgId);
  const { members } = useMembers(orgId);
  const [query, setQuery] = useState("");

  const needle = query.trim().toLowerCase();
  const pickedGroups = groups.filter((group) => value.group_ids.includes(group.id));
  const pickedPeople = members.filter((member) => value.user_ids.includes(member.user_id));
  const groupMatches = groups.filter(
    (group) => !value.group_ids.includes(group.id) && group.name.toLowerCase().includes(needle),
  );
  const peopleMatches = needle
    ? members.filter(
        (member) =>
          !value.user_ids.includes(member.user_id) &&
          `${member.full_name ?? ""} ${member.email}`.toLowerCase().includes(needle),
      )
    : [];
  const suggestions = [
    ...groupMatches.map((group) => ({ kind: "group" as const, group })),
    ...peopleMatches.map((member) => ({ kind: "person" as const, member })),
  ].slice(0, SUGGESTIONS);

  const set = (group_ids: string[], user_ids: string[]) =>
    onChange({ mode: "chosen", group_ids, user_ids });

  return (
    <div className="space-y-2" role="group" aria-label={t("chooseAudience")}>
      {(pickedGroups.length > 0 || pickedPeople.length > 0) && (
        <ul className="flex flex-wrap gap-1.5" aria-label={t("chosenList")}>
          {pickedGroups.map((group) => (
            <Chip
              key={group.id}
              label={group.name}
              remove={t("remove", { name: group.name })}
              disabled={disabled}
              onRemove={() =>
                set(
                  value.group_ids.filter((id) => id !== group.id),
                  value.user_ids,
                )
              }
            >
              <GroupIcon
                icon={group.icon}
                className="h-5 w-5 rounded-full [&_svg]:h-3 [&_svg]:w-3"
              />
            </Chip>
          ))}
          {pickedPeople.map((member) => (
            <Chip
              key={member.user_id}
              label={member.full_name ?? member.email}
              remove={t("remove", { name: member.full_name ?? member.email })}
              disabled={disabled}
              onRemove={() =>
                set(
                  value.group_ids,
                  value.user_ids.filter((id) => id !== member.user_id),
                )
              }
            >
              <User className="text-muted-foreground mx-1 h-3.5 w-3.5" aria-hidden />
            </Chip>
          ))}
        </ul>
      )}
      <div className="relative">
        <Search
          className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2"
          aria-hidden
        />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("searchPlaceholder")}
          aria-label={t("search")}
          disabled={disabled}
          className="pl-8"
        />
      </div>
      {suggestions.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {suggestions.map((suggestion) =>
            suggestion.kind === "group" ? (
              <button
                key={suggestion.group.id}
                type="button"
                disabled={disabled}
                onClick={() => {
                  set([...value.group_ids, suggestion.group.id], value.user_ids);
                  setQuery("");
                }}
                className="hover:bg-accent/50 flex items-center gap-1.5 rounded-full border py-0.5 pr-3 pl-0.5 text-xs"
              >
                <GroupIcon
                  icon={suggestion.group.icon}
                  className="h-5 w-5 rounded-full [&_svg]:h-3 [&_svg]:w-3"
                />
                {suggestion.group.name}
              </button>
            ) : (
              <button
                key={suggestion.member.user_id}
                type="button"
                disabled={disabled}
                onClick={() => {
                  set(value.group_ids, [...value.user_ids, suggestion.member.user_id]);
                  setQuery("");
                }}
                className="hover:bg-accent/50 flex items-center gap-1.5 rounded-full border px-3 py-0.5 text-xs"
              >
                <User className="text-muted-foreground h-3.5 w-3.5" aria-hidden />
                {suggestion.member.full_name ?? suggestion.member.email}
              </button>
            ),
          )}
        </div>
      ) : (
        <p className="text-muted-foreground text-xs">
          {needle ? t("noMatches") : groups.length === 0 ? t("noGroupsYet") : t("typeForPeople")}
        </p>
      )}
    </div>
  );
}

function Chip({
  label,
  remove,
  disabled,
  onRemove,
  children,
}: {
  label: string;
  remove: string;
  disabled?: boolean;
  onRemove: () => void;
  children: React.ReactNode;
}) {
  return (
    <li className="border-foreground/40 bg-accent flex items-center gap-1 rounded-full border py-0.5 pr-1 pl-0.5 text-xs font-medium">
      {children}
      {label}
      <button
        type="button"
        aria-label={remove}
        disabled={disabled}
        onClick={onRemove}
        className="text-muted-foreground hover:text-foreground rounded-full p-0.5"
      >
        <X className="h-3 w-3" />
      </button>
    </li>
  );
}
