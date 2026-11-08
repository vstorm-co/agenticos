"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui";
import {
  OrgSpendingLimit,
  OrgApprovalWaiver,
  OrgPublicLiveData,
  OrgVoiceSettings,
  OrgProactivity,
  OrgAssistant,
  OrgSystemAgents,
} from "@/components/teams";
import { ErrorState } from "@/components/states";
import { usePermissions } from "@/hooks/use-permissions";
import type { Organization } from "@/types";
import { Perm } from "@/types/permissions";
import styles from "./administration.module.css";

export function StartOrganizationSettings({ org }: { org: Organization }) {
  const t = useTranslations("start.administration");
  const tStart = useTranslations("start");
  const { can, isLoaded, error, refetch } = usePermissions();
  if (error)
    return (
      <ErrorState
        title={tStart("loadFailed")}
        cta={{ label: tStart("retry"), onClick: () => void refetch() }}
      />
    );
  if (!isLoaded) return <p role="status">{t("checkingAccess")}</p>;
  return (
    <Tabs defaultValue="governance" className={styles.orgSettings}>
      <TabsList aria-label={t("organization")}>
        <TabsTrigger value="governance">{t("governance")}</TabsTrigger>
        <TabsTrigger value="services">{t("services")}</TabsTrigger>
        {can(Perm.orgSettings) && <TabsTrigger value="voice">{t("voice")}</TabsTrigger>}
      </TabsList>
      <TabsContent value="governance" className="space-y-5">
        {can(Perm.budgetsManage) && <OrgSpendingLimit org={org} />}
        {can(Perm.approvalsDecide) && <OrgApprovalWaiver org={org} />}
        {can(Perm.orgSettings) && <OrgPublicLiveData org={org} />}
        <div className={styles.settingsLinks}>
          <Link href={`/orgs/${org.id}/members`}>{t("allOrganizationSettings")}</Link>
          {can(Perm.orgSettings) && (
            <Link href={`/orgs/${org.id}/retention`}>{t("retention")}</Link>
          )}
          {can(Perm.orgSettings) && (
            <Link href={`/orgs/${org.id}/directory`}>{t("directory")}</Link>
          )}
        </div>
      </TabsContent>
      <TabsContent value="services" className="space-y-5">
        {can(Perm.orgSettings) && <OrgAssistant orgId={org.id} />}
        {can(Perm.budgetsManage) && (
          <>
            <OrgSystemAgents org={org} />
            <OrgProactivity org={org} />
          </>
        )}
      </TabsContent>
      {can(Perm.orgSettings) && (
        <TabsContent value="voice">
          <OrgVoiceSettings org={org} />
        </TabsContent>
      )}
    </Tabs>
  );
}
