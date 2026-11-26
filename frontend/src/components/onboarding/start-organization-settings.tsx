"use client";

import { NativeDisclosure } from "@/components/ui/native-disclosure";

import Link from "next/link";
import { ChevronDown, ShieldCheck, Bot, Mic, ArrowUpRight } from "lucide-react";
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
import { usePermissions } from "@/hooks/use-permissions";
import type { Organization } from "@/types";
import { Perm } from "@/types/permissions";
import { StartSkeleton } from "./start-skeleton";
import { StartBudget } from "./start-budget";
import { StartQuestion, StartStepFailed, StartStepPending } from "./start-question";
import styles from "./guided-start.module.css";

export function StartOrganizationSettings({
  org,
  onContinue,
  onBack,
  active = true,
}: {
  org: Organization;
  onContinue: () => void;
  /** Back to the wizard's previous step, from this step's first question. */
  onBack?: () => void;
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
  if (error) return <StartStepFailed onRetry={() => void refetch()} onBack={onBack} />;
  if (!isLoaded)
    return (
      <StartStepPending onBack={onBack}>
        <StartSkeleton fullPage={false} view={budgetDone ? "organization" : "budget"} />
      </StartStepPending>
    );
  if (showBudget)
    return <StartBudget org={org} onBack={onBack} onContinue={() => setBudgetDone(true)} />;
  return (
    <StartQuestion
      stage="organization"
      index={can(Perm.budgetsManage) ? 1 : 0}
      title={t("workspaceReadyTitle")}
      message={t("workspaceReadyGuide")}
      onBack={can(Perm.budgetsManage) ? () => setBudgetDone(false) : onBack}
      onContinue={onContinue}
    >
      <div className={styles.stack}>
        {(can(Perm.approvalsDecide) || can(Perm.orgSettings)) && (
          <NativeDisclosure className={styles.details}>
            <summary>
              <ShieldCheck size={18} aria-hidden />
              <span>
                <strong>{t("advancedSafety")}</strong>
                <small>{t("advancedSafetyHint")}</small>
              </span>
              <ChevronDown size={16} aria-hidden />
            </summary>
            <div>
              {can(Perm.approvalsDecide) && <OrgApprovalWaiver org={org} />}
              {can(Perm.orgSettings) && <OrgPublicLiveData org={org} />}
              <Link
                href={`/orgs/${org.id}/members?tab=governance`}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("openGovernanceSettings")}{" "}
                <ArrowUpRight size={13} className="inline" aria-hidden />
              </Link>
            </div>
          </NativeDisclosure>
        )}
        {(can(Perm.orgSettings) || can(Perm.budgetsManage)) && (
          <NativeDisclosure className={styles.details}>
            <summary>
              <Bot size={18} aria-hidden />
              <span>
                <strong>{t("advancedAssistants")}</strong>
                <small>{t("advancedAssistantsHint")}</small>
              </span>
              <ChevronDown size={16} aria-hidden />
            </summary>
            <div>
              {can(Perm.orgSettings) && <OrgAssistant orgId={org.id} />}
              {can(Perm.budgetsManage) && (
                <>
                  <OrgSystemAgents org={org} />
                  <OrgProactivity org={org} />
                </>
              )}
              <Link
                href={`/orgs/${org.id}/members?tab=assistant`}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("openAssistantSettings")}{" "}
                <ArrowUpRight size={13} className="inline" aria-hidden />
              </Link>
            </div>
          </NativeDisclosure>
        )}
        {can(Perm.orgSettings) && (
          <NativeDisclosure className={styles.details}>
            <summary>
              <Mic size={18} aria-hidden />
              <span>
                <strong>{t("advancedVoice")}</strong>
                <small>{t("advancedVoiceHint")}</small>
              </span>
              <ChevronDown size={16} aria-hidden />
            </summary>
            <div>
              <OrgVoiceSettings org={org} />
              <Link
                href={`/orgs/${org.id}/members?tab=voice`}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("openVoiceSettings")} <ArrowUpRight size={13} className="inline" aria-hidden />
              </Link>
            </div>
          </NativeDisclosure>
        )}
        {can(Perm.orgSettings) && (
          <Link
            href={`/orgs/${org.id}/members?tab=profile`}
            className="text-muted-foreground text-sm underline underline-offset-4"
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("openOrganizationSettings")}
          </Link>
        )}
      </div>
    </StartQuestion>
  );
}
