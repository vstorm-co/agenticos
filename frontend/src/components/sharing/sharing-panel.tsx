"use client";

import { useState } from "react";
import { Trash2, UserPlus } from "lucide-react";

import { LoadingState } from "@/components/states";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useMembers, useSharing } from "@/hooks";
import { useOrgStore } from "@/stores";
import type { GrantLevel, ResourceGrant, SharingResourceType, Visibility } from "@/types/sharing";
import { useTranslations } from "next-intl";

interface SharingPanelProps {
  resourceType: SharingResourceType;
  resourceId: string;
  /**
   * Sharing is an edit: the server refuses it from anyone who could not change
   * the resource itself. The caller passes that decision in because which
   * permission it is depends on the resource type.
   */
  canManage: boolean;
}

/** What to call the thing being shared, so the copy reads as English. */
const NOUN: Record<SharingResourceType, string> = {
  agent: "agent",
  skill: "skill",
  collection: "collection",
  secret: "secret",
};

/**
 * The two answers this product actually has.
 *
 * `team` is a third value the column accepts and the access rules understand,
 * and it means "anyone whose role reaches team resources" - a role scope with
 * no team behind it, because there is no such thing as a team here. Offering it
 * asked people to choose between a concept the product does not have and one it
 * does. It stays in the database and in `resolve_access` (rows already set to it
 * keep working, and the option below appears for them) but nothing new can be
 * set to it from here.
 */
const VISIBILITY_OPTIONS: {
  value: Visibility;
  /** Catalog key for this visibility's name; `<key>Reaches` says who it reaches. */
  words: string;
}[] = [
  { value: "private", words: "visibilityPrivate" },
  { value: "org", words: "visibilityOrg" },
];

/** Shown only for a row already set to it, so it can be seen and moved off. */
const LEGACY_TEAM = { value: "team" as Visibility, words: "visibilityTeam" };

/**
 * What a share actually reaches, per resource type.
 *
 * Sharing decides who can *pick* a resource in the Builder and who can change
 * it. It does not decide who benefits from it: an agent runs its bindings for
 * everyone who can run the agent, so a key or a collection bound into one is
 * used on behalf of people who cannot see it here. That is deliberate - an
 * agent is an artifact whose author decided what it may reach, and re-checking
 * per caller would make the same agent quietly answer worse for some people
 * than for others. It is also the single thing about this panel somebody would
 * get wrong, so it is written down where the decision is made.
 */
const RUNTIME_NOTE: Partial<Record<SharingResourceType, string>> = {
  secret: "secretRuntimeNote",
  collection: "collectionRuntimeNote",
};

/** Each level's word is in the catalog; `words` names the key. */
const LEVEL_OPTIONS: { value: GrantLevel; words: string }[] = [
  { value: "read", words: "levelRead" },
  { value: "use", words: "levelUse" },
  { value: "edit", words: "levelEdit" },
];

/** Radix hands back a plain string; a level the catalog does not know is a bug, not a default. */
export function toLevel(value: string): GrantLevel {
  const option = LEVEL_OPTIONS.find((candidate) => candidate.value === value);
  if (!option) throw new Error(`Unknown grant level: ${value}`);
  return option.value;
}

/**
 * A grant subject the server could not name is shown by id.
 *
 * Emails are resolved from the organization's members, so a subject whose
 * membership is gone has none - and printing the id is more useful than
 * printing nothing when the row still has to be revoked.
 */
function subjectLabel(grant: ResourceGrant): string {
  return grant.subject_email ?? grant.subject_user_id;
}

/**
 * Who reaches one agent, skill, collection or vault secret.
 *
 * Parameterised by resource type rather than built for agents: the backend
 * generates the same four endpoints per type, and a second copy of this panel
 * would drift from the first the day either one is fixed.
 */
export function SharingPanel({ resourceType, resourceId, canManage }: SharingPanelProps) {
  const t = useTranslations("sharing");
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { members } = useMembers(activeOrgId ?? "");
  const { sharing, isLoading, share, revoke, setVisibility } = useSharing(resourceType, resourceId);

  const [subjectUserId, setSubjectUserId] = useState("");
  const [level, setLevel] = useState<GrantLevel>("read");

  // Two cards, visibility then people - the same two this renders once loaded.
  if (isLoading || !sharing)
    return (
      <div className="space-y-6">
        <LoadingState variant="skeleton-panel" rows={3} />
        <LoadingState variant="skeleton-panel" rows={2} />
      </div>
    );

  const noun = NOUN[resourceType];
  const shared = new Set(sharing.grants.map((grant) => grant.subject_user_id));
  // The owner already has full access, and a grant to someone who is not a
  // member is refused by the server - so neither belongs in the picker.
  const candidates = members.filter(
    (member) => !shared.has(member.user_id) && member.user_id !== sharing.owner_user_id,
  );
  const ownerEmail = members.find((member) => member.user_id === sharing.owner_user_id)?.email;

  function addShare() {
    share.mutate({ subject_user_id: subjectUserId, level });
    setSubjectUserId("");
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("visibility")}</CardTitle>
          <CardDescription>
            Who reaches this {noun} without being named. Sharing adds people on top of this; it
            never takes access away.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {[...VISIBILITY_OPTIONS, ...(sharing.visibility === "team" ? [LEGACY_TEAM] : [])].map(
            (option) => {
              const id = `visibility-${option.value}`;
              return (
                <div key={option.value} className="flex items-start gap-3 rounded-md border p-3">
                  <input
                    type="radio"
                    id={id}
                    name="visibility"
                    className="mt-1"
                    checked={sharing.visibility === option.value}
                    disabled={!canManage || setVisibility.isPending}
                    onChange={() => setVisibility.mutate(option.value)}
                  />
                  <div className="space-y-1">
                    <Label htmlFor={id}>{t(option.words)}</Label>
                    <p className="text-muted-foreground text-sm">
                      {t(`${option.words}Reaches`, { noun })}
                    </p>
                  </div>
                </div>
              );
            },
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("people")}</CardTitle>
          <CardDescription>
            A share lifts one person&apos;s access to this {noun} without changing their role
            anywhere else. Can view sees the configuration, can use also runs it, can edit also
            changes it.
          </CardDescription>
          {RUNTIME_NOTE[resourceType] && (
            <p className="text-muted-foreground border-border mt-2 border-l-2 pl-3 text-sm">
              {t(RUNTIME_NOTE[resourceType]!)}
            </p>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {ownerEmail && <p className="text-muted-foreground text-sm">Owned by {ownerEmail}</p>}

          {sharing.grants.length === 0 && (
            <p className="text-muted-foreground text-sm">{t("notSharedWithAnyone")}</p>
          )}

          {sharing.grants.map((grant) => {
            const name = subjectLabel(grant);
            const id = `level-${grant.subject_user_id}`;
            return (
              <div key={grant.id} className="flex items-center gap-3 rounded-md border p-3">
                <span className="min-w-0 flex-1 truncate text-sm">{name}</span>
                <Label htmlFor={id} className="sr-only">
                  Access for {name}
                </Label>
                <Select
                  value={grant.level}
                  disabled={!canManage}
                  onValueChange={(value) =>
                    share.mutate({
                      subject_user_id: grant.subject_user_id,
                      level: toLevel(value),
                    })
                  }
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
                    aria-label={`Remove ${name}`}
                    disabled={revoke.isPending}
                    onClick={() => revoke.mutate(grant.subject_user_id)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            );
          })}

          {canManage && (
            <div className="flex flex-wrap items-end gap-3 border-t pt-4">
              <div className="min-w-56 flex-1 space-y-2">
                <Label htmlFor="share-with">{t("addSomeone")}</Label>
                <Select
                  value={subjectUserId}
                  onValueChange={setSubjectUserId}
                  disabled={candidates.length === 0}
                >
                  <SelectTrigger id="share-with">
                    <SelectValue
                      placeholder={
                        candidates.length === 0 ? t("everyoneAlreadyHasAccess") : t("chooseMember")
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {candidates.map((member) => (
                      <SelectItem key={member.user_id} value={member.user_id}>
                        {member.email}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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
              <Button onClick={addShare} disabled={subjectUserId === "" || share.isPending}>
                <UserPlus className="h-4 w-4" />
                {t("share")}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
