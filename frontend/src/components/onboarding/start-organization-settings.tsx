"use client";

import Link from "next/link";
import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { rememberStartQuestion } from "./start-position";
import { useTranslations } from "next-intl";
import {
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
import { StartSkeleton } from "./start-skeleton";
import { StartBudget } from "./start-budget";
import { StartQuestion } from "./start-question";
import styles from "./guided-start.module.css";

export function StartOrganizationSettings({
  org,
  onContinue,
  active = true,
}: {
  org: Organization;
  onContinue: () => void;
  active?: boolean;
}) {
  const t = useTranslations("start.guided");
  const { can, isLoaded, error, refetch } = usePermissions();
  const search = useSearchParams();
  const [budgetDone, setBudgetDone] = useState(
    search.get("workspace") === org.id &&
      search.get("start-step") === "admin.organization" &&
      search.get("question") === "advanced",
  );
  const showBudget = !budgetDone && can(Perm.budgetsManage);
  useEffect(() => {
    if (active && isLoaded)
      rememberStartQuestion("admin.organization", org.id, showBudget ? "budget" : "advanced");
  }, [active, isLoaded, org.id, showBudget]);
  if (error)
    return (
      <ErrorState
        title={t("loadFailed")}
        cta={{ label: t("retry"), onClick: () => void refetch() }}
      />
    );
  if (!isLoaded)
    return <StartSkeleton fullPage={false} view={budgetDone ? "organization" : "budget"} />;
  if (showBudget) return <StartBudget org={org} onContinue={() => setBudgetDone(true)} />;
  return (
    <StartQuestion
      index={can(Perm.budgetsManage) ? 1 : 0}
      total={can(Perm.budgetsManage) ? 2 : 1}
      title={t("workspaceReadyTitle")}
      message={t("workspaceReadyGuide")}
      onBack={can(Perm.budgetsManage) ? () => setBudgetDone(false) : undefined}
      onContinue={onContinue}
    >
      <div className={styles.preview}>
        <strong>{t("readyForPeople")}</strong>
        <p>{t("readyForPeopleBody", { workspace: org.name })}</p>
      </div>
      <p className={`${styles.hint} my-6`}>{t("advancedOptional")}</p>
      <div className={styles.stack}>
        {(can(Perm.approvalsDecide) || can(Perm.orgSettings)) && (
          <details className={styles.details}>
            <summary>{t("advancedSafety")}</summary>
            <div>
              {can(Perm.approvalsDecide) && <OrgApprovalWaiver org={org} />}
              {can(Perm.orgSettings) && <OrgPublicLiveData org={org} />}
            </div>
          </details>
        )}
        {(can(Perm.orgSettings) || can(Perm.budgetsManage)) && (
          <details className={styles.details}>
            <summary>{t("advancedAssistants")}</summary>
            <div>
              {can(Perm.orgSettings) && <OrgAssistant orgId={org.id} />}
              {can(Perm.budgetsManage) && (
                <>
                  <OrgSystemAgents org={org} />
                  <OrgProactivity org={org} />
                </>
              )}
            </div>
          </details>
        )}
        {can(Perm.orgSettings) && (
          <details className={styles.details}>
            <summary>{t("advancedVoice")}</summary>
            <div>
              <OrgVoiceSettings org={org} />
            </div>
          </details>
        )}
        <Link
          href={`/orgs/${org.id}/members`}
          className="text-muted-foreground text-sm underline underline-offset-4"
          target="_blank"
          rel="noopener noreferrer"
        >
          {t("openOrganizationSettings")}
        </Link>
      </div>
    </StartQuestion>
  );
}
