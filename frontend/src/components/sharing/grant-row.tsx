"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { GroupIcon } from "@/components/groups/group-icon";
import {
  EntityAvatar,
  IconButton,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { GroupIcon as GroupIconName } from "@/types/groups";
import type { GrantSubject, ResourceGrant, ShareInput, SharingResourceType } from "@/types/sharing";
import { EditDataConfirm } from "./edit-data-confirm";
import { levelOptions, shareInput, subjectLabel, subjectOf, toLevel } from "./grants";

interface GrantRowProps {
  grant: ResourceGrant;
  /** Which levels this kind of resource offers. */
  resourceType: SharingResourceType;
  /** Whether the caller may give "including data" - the server's answer, never worked out here. */
  mayGrantEditData: boolean;
  /** The member's full name, when they have one: the confirmation names them as the audit does. */
  fullName?: string | null;
  /** The group's own icon, when the grant is to a group the organization still has. */
  groupIcon: GroupIconName | null;
  canManage: boolean;
  revoking: boolean;
  onShare: (input: ShareInput) => void;
  onRevoke: (subject: GrantSubject) => void;
}

/**
 * One member or group the resource is shared with, at what level.
 *
 * A face or the group's icon, the name, and the level as a quiet control on
 * the right - the row reads as a person first and a setting second, the way a
 * document's share list does. A level change is the same call that created the
 * share - the endpoint is an upsert keyed on the subject - so the row sends the
 * subject back with it.
 */
export function GrantRow({
  resourceType,
  grant,
  mayGrantEditData,
  fullName,
  groupIcon,
  canManage,
  revoking,
  onShare,
  onRevoke,
}: GrantRowProps) {
  const t = useTranslations("sharing");
  const tc = useTranslations("common");
  const [asking, setAsking] = useState(false);
  const subject = subjectOf(grant);
  const name = subjectLabel(grant);
  const id = `level-${grant.id}`;

  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      {subject.kind === "group" ? (
        <>
          <GroupIcon icon={groupIcon} className="size-8 rounded-full" />
          <span className="sr-only">{t("groupSubject")}</span>
        </>
      ) : (
        <EntityAvatar
          seed={subject.id}
          name={name}
          imageSrc={`/api/users/avatar/${subject.id}`}
          className="size-8 shrink-0"
          ariaHidden
        />
      )}
      <span className="min-w-0 flex-1 truncate text-sm">{name}</span>
      <Label htmlFor={id} className="sr-only">
        {t("accessFor", { name })}
      </Label>
      <Select
        value={grant.level}
        disabled={!canManage}
        onValueChange={(value) => {
          const level = toLevel(value);
          // "Data included" says what it does first; any other level goes at once.
          if (level === "edit_data") setAsking(true);
          else onShare(shareInput(subject, level));
        }}
      >
        <SelectTrigger
          id={id}
          className="text-muted-foreground hover:text-foreground h-8 w-auto gap-1.5 border-transparent bg-transparent px-2.5 shadow-none"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="end">
          {levelOptions(resourceType, { mayGrantEditData, held: grant.level }).map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {t(option.words)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <EditDataConfirm
        open={asking}
        onOpenChange={setAsking}
        name={fullName || name}
        kind={subject.kind}
        onConfirm={() => {
          setAsking(false);
          onShare(shareInput(subject, "edit_data"));
        }}
      />
      {canManage && (
        <IconButton
          aria-label={tc("removeNamed", { name })}
          disabled={revoking}
          onClick={() => onRevoke(subject)}
          className="text-muted-foreground hover:text-destructive"
        >
          <X />
        </IconButton>
      )}
    </li>
  );
}
