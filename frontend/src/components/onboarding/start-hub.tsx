"use client";

import Link from "next/link";
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
  if (state.isLoading || state.waitingForScope) return <LoadingState />;
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
    <div className="mx-auto w-full max-w-4xl space-y-7 px-6 py-8">
      <div className="flex items-center justify-between">
        <Link href="/chat" className="font-semibold">
          {appName}
        </Link>
        <StartLanguage />
      </div>
      <header className="space-y-2">
        <p className="text-muted-foreground text-sm">{data.organization_name}</p>
        <h1 className="text-3xl font-semibold tracking-tight">
          {t(data.has_result ? "returnTitle" : "title")}
        </h1>
        <p className="text-muted-foreground">{t("intro")}</p>
      </header>
      {data.has_result && data.latest_conversation_id && (
        <Link
          className="inline-flex rounded-lg border px-4 py-2 text-sm"
          href={`/chat?id=${data.latest_conversation_id}`}
        >
          {t("lastResult")}
        </Link>
      )}
      <StartTasks key={data.organization_id} data={data} />
      {data.goal && <p className="text-muted-foreground text-xs">{t("progressSaved")}</p>}
      {data.has_result && <StartNextSteps orgId={data.organization_id} />}
      <footer className="flex flex-wrap items-center gap-4 border-t pt-5 text-sm">
        <Link href="/chat" className="underline">
          {t("ownTask")}
        </Link>
        <Link href="/orgs" className="underline">
          {t("organizations")}
        </Link>
        <Button
          variant="ghost"
          onClick={() => {
            router.push("/dashboard");
            openTour();
          }}
        >
          {t("tour")}
        </Button>
      </footer>
    </div>
  );
}
