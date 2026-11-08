"use client";

import { useState, useSyncExternalStore } from "react";
import { useTranslations } from "next-intl";
import { MailPlus, Link2, ArrowRight, Settings2 } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui";
import { InviteMemberDialog, InviteLinkDialog } from "@/components/teams";
import { ErrorState } from "@/components/states";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import { isLoopbackAddress } from "@/lib/local-server";
import type { Organization } from "@/types";
import styles from "./administration.module.css";

const subscribe = () => () => {};
export function StartInviteTeam({
  org,
  onContinue,
}: {
  org: Organization;
  onContinue: () => void;
}) {
  const t = useTranslations("start.administration");
  const tStart = useTranslations("start");
  const { can, isLoading, error, refetch } = usePermissions();
  const [inviting, setInviting] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);
  const local = useSyncExternalStore(
    subscribe,
    () => isLoopbackAddress(window.location.origin),
    () => false,
  );
  if (error)
    return (
      <ErrorState
        title={tStart("loadFailed")}
        cta={{ label: tStart("retry"), onClick: () => void refetch() }}
      />
    );
  return (
    <section className={styles.teamStage}>
      <p>{t("teamIntro", { workspace: org.name })}</p>
      {local && (
        <p role="note" className={styles.notice}>
          {t("reachableAddress")}
        </p>
      )}
      {can(Perm.membersManage) && (
        <div className={styles.actions}>
          <Button onClick={() => setInviting(true)} disabled={local}>
            <MailPlus size={16} aria-hidden />
            {t("inviteEmail")}
          </Button>
          <Button variant="outline" onClick={() => setLinkOpen(true)} disabled={local}>
            <Link2 size={16} aria-hidden />
            {t("inviteLink")}
          </Button>
        </div>
      )}
      {!isLoading && !can(Perm.membersManage) && <p role="note">{t("cannotInvite")}</p>}
      <div className={styles.settingsLinks}>
        <Link href={`/orgs/${org.id}/members`}>
          <Settings2 size={15} aria-hidden />
          {t("manageMembers")}
        </Link>
        {can(Perm.rolesManage) && <Link href={`/orgs/${org.id}/roles`}>{t("manageRoles")}</Link>}
        {can(Perm.membersManage) && (
          <Link href={`/orgs/${org.id}/groups`}>{t("manageGroups")}</Link>
        )}
      </div>
      <Button onClick={onContinue}>
        {t("continueSetup")}
        <ArrowRight size={15} aria-hidden />
      </Button>
      {can(Perm.membersManage) && (
        <>
          <InviteMemberDialog orgId={org.id} open={inviting} onOpenChange={setInviting} />
          <InviteLinkDialog orgId={org.id} open={linkOpen} onOpenChange={setLinkOpen} />
        </>
      )}
    </section>
  );
}
