"use client";

import { Trash2, Users } from "lucide-react";
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
import type { GrantSubject, ResourceGrant, ShareInput } from "@/types/sharing";
import { LEVEL_OPTIONS, shareInput, subjectLabel, subjectOf, toLevel } from "./grants";

interface GrantRowProps {
  grant: ResourceGrant;
  canManage: boolean;
  revoking: boolean;
  onShare: (input: ShareInput) => void;
  onRevoke: (subject: GrantSubject) => void;
}

/**
 * One member or group the resource is shared with, at what level.
 *
 * A level change is the same call that created the share - the endpoint is an
 * upsert keyed on the subject - so the row sends the subject back with it.
 */
export function GrantRow({ grant, canManage, revoking, onShare, onRevoke }: GrantRowProps) {
  const t = useTranslations("sharing");
  const tc = useTranslations("common");
  const subject = subjectOf(grant);
  const name = subjectLabel(grant);
  const id = `level-${grant.id}`;

  return (
    <div className="flex items-center gap-3 rounded-md border p-3">
      {subject.kind === "group" && (
        <>
          <Users className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
          <span className="sr-only">{t("groupSubject")}</span>
        </>
      )}
      <span className="min-w-0 flex-1 truncate text-sm">{name}</span>
      <Label htmlFor={id} className="sr-only">
        {t("accessFor", { name })}
      </Label>
      <Select
        value={grant.level}
        disabled={!canManage}
        onValueChange={(value) => onShare(shareInput(subject, toLevel(value)))}
      >
        <SelectTrigger id={id} className="w-36">
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
      {canManage && (
        <Button
          variant="ghost"
          size="sm"
          aria-label={tc("removeNamed", { name })}
          disabled={revoking}
          onClick={() => onRevoke(subject)}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}
