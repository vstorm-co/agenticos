"use client";

import { LoadingState } from "@/components/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Label } from "@/components/ui";
import { useGroups, useMembers, useSharing } from "@/hooks";
import { useOrgStore } from "@/stores";
import type { SharingResourceType, Visibility } from "@/types/sharing";
import { useTranslations } from "next-intl";
import { AddShare } from "./add-share";
import { GrantRow } from "./grant-row";

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

/**
 * Who reaches one agent, skill, collection or vault secret.
 *
 * Parameterised by resource type rather than built for agents: the backend
 * generates the same endpoints per type, and a second copy of this panel would
 * drift from the first the day either one is fixed.
 */
export function SharingPanel({ resourceType, resourceId, canManage }: SharingPanelProps) {
  const t = useTranslations("sharing");
  const activeOrgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const { members } = useMembers(activeOrgId);
  const { groups } = useGroups(activeOrgId);
  const { sharing, isLoading, share, revoke, setVisibility } = useSharing(resourceType, resourceId);

  // Two cards, visibility then people - the same two this renders once loaded.
  if (isLoading || !sharing)
    return (
      <div className="space-y-6">
        <LoadingState variant="skeleton-panel" rows={3} />
        <LoadingState variant="skeleton-panel" rows={2} />
      </div>
    );

  const shared = new Set(
    sharing.grants.map((grant) => grant.subject_user_id ?? grant.subject_group_id),
  );
  // The owner already has full access, and a grant to someone who is not a
  // member is refused by the server - so neither belongs in the picker.
  const memberCandidates = members.filter(
    (member) => !shared.has(member.user_id) && member.user_id !== sharing.owner_user_id,
  );
  const groupCandidates = groups.filter((group) => !shared.has(group.id));
  const ownerEmail = members.find((member) => member.user_id === sharing.owner_user_id)?.email;
  const runtimeNote = RUNTIME_NOTE[resourceType];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("visibility")}</CardTitle>
          <CardDescription>{t("visibilityReaches", { resource: resourceType })}</CardDescription>
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
                      {t(`${option.words}Reaches`, { resource: resourceType })}
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
          <CardTitle>{t("peopleAndGroups")}</CardTitle>
          <CardDescription>{t("peopleReaches", { resource: resourceType })}</CardDescription>
          {runtimeNote && (
            <p className="text-muted-foreground border-border mt-2 border-l-2 pl-3 text-sm">
              {t(runtimeNote)}
            </p>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {ownerEmail && (
            <p className="text-muted-foreground text-sm">{t("ownedBy", { email: ownerEmail })}</p>
          )}

          {sharing.grants.length === 0 && (
            <p className="text-muted-foreground text-sm">{t("notSharedWithAnyone")}</p>
          )}

          {sharing.grants.map((grant) => (
            <GrantRow
              key={grant.id}
              grant={grant}
              canManage={canManage}
              revoking={revoke.isPending}
              onShare={(input) => share.mutate(input)}
              onRevoke={(subject) => revoke.mutate(subject)}
            />
          ))}

          {canManage && (
            <AddShare
              members={memberCandidates}
              groups={groupCandidates}
              pending={share.isPending}
              onShare={(input) => share.mutate(input)}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
