"use client";

import Link from "next/link";
import { AvatarFace } from "@/components/ui/avatar-face";
import { ArrowRight, Building2, CheckCircle2, Compass, ArrowUpRight } from "lucide-react";
import { BrandMark } from "@/components/branding/brand-mark";
import styles from "./workbench.module.css";
import { useTranslations } from "next-intl";
import { useRouter } from "@/lib/locale-navigation";
import { Button } from "@/components/ui";
import { ErrorState } from "@/components/states";
import { useStart } from "@/hooks/use-start";
import { useOrganizations, useOrganizationList } from "@/hooks/use-organizations";
import { useOnboardingStore } from "@/stores/onboarding-store";
import { useBranding } from "@/components/branding/branding-provider";
import { StartLanguage } from "./start-language";
import { StartNextSteps } from "./start-next-steps";
import { useAuthStore } from "@/stores/auth-store";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import { StartAdministration } from "./start-administration";
import { StartTasks } from "./start-tasks";
import { StartMember } from "./start-member";
import { StartSkeleton } from "./start-skeleton";
import { StartFinish } from "./start-finish";

export function StartHub() {
  const { activeOrg } = useOrganizations();
  const appAdmin = useAuthStore((state) => state.user?.is_app_admin === true);
  const permissions = usePermissions();
  const organizations = useOrganizationList();
  const state = useStart();
  const t = useTranslations("start");
  const { appName } = useBranding();
  const router = useRouter();
  const openTour = useOnboardingStore((s) => s.openTour);
  if (
    appAdmin ||
    (activeOrg &&
      !activeOrg.is_personal &&
      permissions.isLoaded &&
      permissions.can(Perm.orgSettings))
  )
    return <StartAdministration appAdmin={appAdmin} />;
  if (activeOrg && !activeOrg.is_personal && permissions.error)
    return (
      <ErrorState
        title={t("loadFailed")}
        cta={{ label: t("retry"), onClick: () => void permissions.refetch() }}
      />
    );
  if (activeOrg && !activeOrg.is_personal && !permissions.isLoaded && !permissions.error)
    return <StartSkeleton view="welcome" steps={4} />;
  if (organizations.error)
    return (
      <ErrorState
        title={t("loadFailed")}
        cta={{ label: t("retry"), onClick: () => void organizations.refetch() }}
      />
    );
  if (organizations.isSuccess && !organizations.data?.length)
    return (
      <section className="mx-auto max-w-xl space-y-4 p-6">
        <h1 className="text-2xl font-semibold">{t("noOrganization")}</h1>
        <p>{t("noOrganizationHint")}</p>
        <Link href="/orgs" className="underline">
          {t("organizations")}
        </Link>
      </section>
    );
  if (state.isLoading || state.waitingForScope) return <StartSkeleton view="welcome" steps={4} />;
  if (state.error || !state.data)
    return (
      <section className="mx-auto max-w-2xl space-y-4 p-6">
        <ErrorState
          title={t("loadFailed")}
          description={t("loadHint")}
          cta={{ label: t("retry"), onClick: () => void state.refetch() }}
        />
        <Link href="/orgs" className="text-sm underline">
          {t("organizations")}
        </Link>
      </section>
    );
  const data = state.data;
  if (!data.has_activity && !data.has_result && !data.completed)
    return <StartMember key={data.organization_id} data={data} />;
  return (
    <div className={styles.shell}>
      <div className={styles.frame}>
        <nav className={styles.topbar} aria-label={appName}>
          <div className={styles.identity}>
            <Link href="/chat" className={styles.brand}>
              <BrandMark size={28} />
              {appName}
            </Link>
            <span className={styles.workspace}>
              <Building2 size={14} aria-hidden />
              {data.organization_name}
            </span>
          </div>
          <div className={styles.topActions}>
            <StartLanguage />
            <Link href="/chat" className={styles.openApp}>
              {t("workbench.openApp")}
              <ArrowUpRight size={15} aria-hidden />
            </Link>
          </div>
        </nav>
        <header className={styles.intro}>
          <div className={styles.titleRow}>
            <span className={styles.welcomeMark} aria-hidden="true">
              <AvatarFace seed="agenticos" background={false} />
            </span>
            <h1>{t(data.has_result ? "returnTitle" : "workbench.title")}</h1>
          </div>
          <p>{t("workbench.intro")}</p>
        </header>
        {data.has_result && data.latest_conversation_id && (
          <Link className={styles.lastResult} href={`/chat?id=${data.latest_conversation_id}`}>
            <CheckCircle2 size={18} aria-hidden />
            <span>{t("lastResult")}</span>
            <ArrowRight size={16} aria-hidden />
          </Link>
        )}
        <div className="space-y-6">
          <StartTasks key={data.organization_id} data={data} />
          <StartFinish key={data.organization_id} />
        </div>
        {data.has_result && <StartNextSteps orgId={data.organization_id} />}
        <footer className={styles.footer}>
          <Link href="/orgs">
            <Building2 size={14} aria-hidden />
            {t("organizations")}
          </Link>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              router.push("/dashboard");
              openTour();
            }}
          >
            <Compass size={14} aria-hidden />
            {t("tour")}
          </Button>
        </footer>
      </div>
    </div>
  );
}
