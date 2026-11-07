"use client";

import Link from "next/link";
import {
  ArrowRight,
  Building2,
  Check,
  CheckCircle2,
  ChevronRight,
  Compass,
  MessageSquare,
  MousePointer2,
  PencilLine,
  Play,
} from "lucide-react";
import { BrandMark } from "@/components/branding/brand-mark";
import styles from "./start.module.css";
import { useTranslations } from "next-intl";
import { useRouter } from "@/lib/locale-navigation";
import { Button } from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";
import { useStart } from "@/hooks/use-start";
import { useOrganizations, useOrganizationList } from "@/hooks/use-organizations";
import { useOnboardingStore } from "@/stores/onboarding-store";
import { useBranding } from "@/components/branding/branding-provider";
import { StartLanguage } from "./start-language";
import { StartNextSteps } from "./start-next-steps";
import { StartTasks } from "./start-tasks";

export function StartHub() {
  useOrganizations();
  const organizations = useOrganizationList();
  const state = useStart();
  const t = useTranslations("start");
  const { appName } = useBranding();
  const router = useRouter();
  const openTour = useOnboardingStore((s) => s.openTour);
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
  if (state.isLoading || state.waitingForScope)
    return (
      <LoadingState variant="skeleton-cards" rows={3} className="mx-auto max-w-5xl px-6 py-24" />
    );
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
  return (
    <div className={styles.shell}>
      <div className={styles.frame}>
        <nav className={styles.topbar} aria-label={appName}>
          <Link href="/chat" className={styles.brand}>
            <BrandMark size={32} />
            {appName}
          </Link>
          <StartLanguage />
        </nav>
        <header className={styles.hero}>
          <p className={styles.workspace}>
            <Building2 size={14} aria-hidden />
            {data.organization_name}
          </p>
          <h1 className={styles.title}>{t(data.has_result ? "returnTitle" : "title")}</h1>
          <p className={styles.intro}>{t("intro")}</p>
          <div className={styles.path}>
            <span>
              <MousePointer2 size={13} aria-hidden />
              {t("chooseStep")}
            </span>
            <ChevronRight size={12} aria-hidden />
            <span>
              <PencilLine size={13} aria-hidden />
              {t("editStep")}
            </span>
            <ChevronRight size={12} aria-hidden />
            <span>
              <Play size={13} aria-hidden />
              {t("runStep")}
            </span>
          </div>
        </header>
        {data.has_result && data.latest_conversation_id && (
          <Link className={styles.result} href={`/chat?id=${data.latest_conversation_id}`}>
            <span className="flex items-center gap-3">
              <CheckCircle2 size={20} aria-hidden />
              {t("lastResult")}
            </span>
            <ArrowRight size={16} aria-hidden />
          </Link>
        )}
        <StartTasks key={data.organization_id} data={data} />
        {data.goal && (
          <p className={styles.saved}>
            <Check size={14} aria-hidden />
            {t("progressSaved", { task: t(`examples.${data.goal}.title`) })}
          </p>
        )}
        {data.has_result && <StartNextSteps orgId={data.organization_id} />}
        <footer className={styles.footer}>
          <Link href="/chat">
            <MessageSquare size={15} aria-hidden />
            {t("ownTask")}
          </Link>
          <Link href="/orgs">
            <Building2 size={15} aria-hidden />
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
            <Compass size={15} aria-hidden />
            {t("tour")}
          </Button>
        </footer>
      </div>
    </div>
  );
}
