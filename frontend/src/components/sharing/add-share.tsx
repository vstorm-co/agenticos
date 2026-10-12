"use client";

import { useState } from "react";
import { UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  EntityAvatar,
  Label,
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { GroupIcon } from "@/components/groups/group-icon";
import type { Group } from "@/types/groups";
import type { OrganizationMember } from "@/types";
import type { GrantLevel, ShareInput } from "@/types/sharing";
import { encodeSubject, LEVEL_OPTIONS, parseSubject, shareInput, toLevel } from "./grants";

interface AddShareProps {
  /** Members who do not reach the resource yet - the owner and the shared already left out. */
  members: OrganizationMember[];
  /** Groups the resource is not shared with yet. */
  groups: Group[];
  pending: boolean;
  onShare: (input: ShareInput) => void;
}

/**
 * The row that shares a resource with one more member or group.
 *
 * One picker for both, grouped under two headings, because "who else should
 * reach this" is one question whichever kind of answer it gets. It sits at the
 * top of the panel, as a document's share box does: adding somebody is what the
 * panel is opened for, and the list under it is what that changed.
 */
export function AddShare({ members, groups, pending, onShare }: AddShareProps) {
  const t = useTranslations("sharing");
  const [subject, setSubject] = useState("");
  const [level, setLevel] = useState<GrantLevel>("read");
  const empty = members.length === 0 && groups.length === 0;

  function submit() {
    onShare(shareInput(parseSubject(subject), level));
    setSubject("");
  }

  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="min-w-56 flex-1 space-y-2">
        <Label htmlFor="share-with">{t("addSubject")}</Label>
        <Select value={subject} onValueChange={setSubject} disabled={empty}>
          <SelectTrigger id="share-with">
            <SelectValue placeholder={empty ? t("everyoneAlreadyHasAccess") : t("chooseSubject")} />
          </SelectTrigger>
          <SelectContent>
            {groups.length > 0 && (
              <SelectGroup>
                <SelectLabel>{t("groupsHeading")}</SelectLabel>
                {groups.map((group) => (
                  <SelectItem key={group.id} value={encodeSubject({ kind: "group", id: group.id })}>
                    <GroupIcon icon={group.icon} className="size-5 rounded-full [&_svg]:size-3" />
                    {group.name}
                  </SelectItem>
                ))}
              </SelectGroup>
            )}
            {members.length > 0 && (
              <SelectGroup>
                <SelectLabel>{t("membersHeading")}</SelectLabel>
                {members.map((member) => (
                  <SelectItem
                    key={member.user_id}
                    value={encodeSubject({ kind: "user", id: member.user_id })}
                  >
                    <EntityAvatar
                      seed={member.user_id}
                      name={member.full_name || member.email}
                      imageSrc={`/api/users/avatar/${member.user_id}`}
                      className="h-5 w-5 shrink-0 text-[9px]"
                      ariaHidden
                    />
                    {member.email}
                  </SelectItem>
                ))}
              </SelectGroup>
            )}
          </SelectContent>
        </Select>
      </div>
      <div className="w-36 space-y-2">
        <Label htmlFor="share-level">{t("access")}</Label>
        <Select value={level} onValueChange={(value) => setLevel(toLevel(value))}>
          <SelectTrigger id="share-level">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {LEVEL_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {t(option.words)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Button onClick={submit} disabled={subject === "" || pending}>
        <UserPlus className="h-4 w-4" />
        {t("share")}
      </Button>
    </div>
  );
}
