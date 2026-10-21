"use client";

import { useState } from "react";
import { UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { Group } from "@/types/groups";
import type { OrganizationMember } from "@/types";
import type { GrantLevel, ShareInput } from "@/types/sharing";
import { LEVEL_OPTIONS, parseSubject, shareInput, toLevel } from "./grants";
import { SubjectPicker } from "./subject-picker";

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
 * reach this" is one question whichever kind of answer it gets - searched by
 * typing a name or an address.
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
    <div className="flex flex-wrap items-end gap-3 border-t pt-4">
      <div className="min-w-56 flex-1 space-y-2">
        <Label htmlFor="share-with">{t("addSubject")}</Label>
        <SubjectPicker
          id="share-with"
          members={members}
          groups={groups}
          value={subject}
          onChange={setSubject}
          placeholder={empty ? t("everyoneAlreadyHasAccess") : t("chooseSubject")}
          disabled={empty}
        />
      </div>
      <div className="w-40 space-y-2">
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
