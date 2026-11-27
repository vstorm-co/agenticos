"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useDeploymentStart } from "@/hooks/use-deployment-start";
import { useOrganizations, useOrganizationList } from "@/hooks/use-organizations";
import { ErrorState } from "@/components/states";
import { availableStartScopes } from "@/lib/onboarding/scopes";
import { StartSkeleton } from "./start-skeleton";
import { StartScopeProvider } from "./start-scope-context";
import { StartScopeProgress } from "./start-scope-progress";
import { StartSharedJourney } from "./start-shared-journey";
import { StartWorkspace } from "./start-workspace";
import styles from "./administration.module.css";

/** App administrators can configure a deployment before creating its first organization. */
export function StartDeploymentEntry() {
  const t = useTranslations("start.scopes");
  const common = useTranslations("common");
  const state = useDeploymentStart();
  const organizations = useOrganizationList();
  const { switchOrg } = useOrganizations();
  const [review, setReview] = useState(false);
  if (!state.allowed) return <StartSkeleton view="deployment" />;
  if (state.error || organizations.error)
    return (
      <ErrorState
        title={t("loadFailed")}
        cta={{
          label: common("retry"),
          onClick: () => {
            void state.refetch();
            void organizations.refetch();
          },
        }}
      />
    );
  if (!state.data || state.isLoading || organizations.isPending)
    return <StartSkeleton view="deployment" />;
  const scopes = availableStartScopes(state.data);
  const deployment = scopes.find((scope) => scope.scope === "deployment");
  if (deployment && !deployment.completed && !review) setReview(true);
  if (!deployment)
    return (
      <ErrorState
        title={t("loadFailed")}
        cta={{ label: common("retry"), onClick: () => void state.refetch() }}
      />
    );
  return (
    <StartScopeProvider
      value={{
        scopes,
        current: "deployment",
        select: () => setReview(true),
        pending: state.save.isPending,
        failed: state.save.isError,
        continueReview: deployment.completed && review ? () => setReview(false) : undefined,
      }}
    >
      {deployment.completed && !review ? (
        <div className={styles.shell}>
          <div className={styles.frame}>
            <Link href="/chat" className="text-sm underline">
              {t("openApp")}
            </Link>
            <StartScopeProgress />
            <h1 className="text-2xl font-semibold">{t("workspaceTitle")}</h1>
            <p className="text-muted-foreground mt-3 mb-6">{t("workspaceHint")}</p>
            <StartWorkspace
              organizations={organizations.data ?? []}
              activeOrgId={null}
              onSelect={switchOrg}
            />
          </div>
        </div>
      ) : (
        <StartSharedJourney
          scope="deployment"
          organizations={organizations.data ?? []}
          currentStep={deployment.current_step}
          onSelect={switchOrg}
          onComplete={() =>
            state.save.mutate({ completed: true }, { onSuccess: () => setReview(false) })
          }
          pending={state.save.isPending}
        />
      )}
    </StartScopeProvider>
  );
}
