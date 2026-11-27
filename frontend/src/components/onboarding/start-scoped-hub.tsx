"use client";

import { useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useStart } from "@/hooks/use-start";
import { useChanged } from "@/hooks/use-changed";
import { useOrganizations, useOrganizationList } from "@/hooks/use-organizations";
import { useAuthStore, useOrgStore } from "@/stores";
import { START_SCOPES, type Onboarding, type StartScope } from "@/lib/onboarding-api";
import {
  availableStartScopes,
  canReviewStartScope,
  personalStartStep,
  scopeForStartStep,
} from "@/lib/onboarding/scopes";
import { setUrlParam } from "@/lib/utils";
import { Button } from "@/components/ui";
import { StartScopeProvider } from "./start-scope-context";
import { StartScopeProgress } from "./start-scope-progress";
import { StartSharedJourney } from "./start-shared-journey";
import { StartPreferences } from "./start-preferences";
import { StartMember } from "./start-member";
import styles from "./administration.module.css";
import { StartSkeleton } from "./start-skeleton";
import { rememberStartPosition } from "./start-position";

/** Selection reviews earlier stages; server state determines which stage is still required. */
export function StartScopedHub({ data, children }: { data: Onboarding; children?: ReactNode }) {
  const t = useTranslations("start.scopes");
  const state = useStart();
  const { activeOrg, switchOrg } = useOrganizations();
  const organizations = useOrganizationList();
  const userId = useAuthStore((store) => store.user?.id);
  const search = useSearchParams();
  const scopes = availableStartScopes(data);
  const requested =
    START_SCOPES.find((scope) => scope === search.get("start-scope")) ??
    scopeForStartStep(search.get("start-step"));
  const required = data.active_scope ?? scopes.find((scope) => !scope.completed)?.scope ?? null;
  const [review, setReview] = useState<StartScope | null>(() =>
    requested && canReviewStartScope(scopes, requested) ? requested : required,
  );
  const [preferencesDone, setPreferencesDone] = useState(false);
  const changed = useChanged(`${userId}:${data.organization_id}`);
  if (changed) {
    setReview(required);
    setPreferencesDone(false);
  }
  if (review && !canReviewStartScope(scopes, review)) setReview(required);
  const current = review && canReviewStartScope(scopes, review) ? review : required;
  const reviewingComplete =
    current !== null &&
    current !== "personal" &&
    current !== required &&
    scopes.some((scope) => scope.scope === current && scope.completed);
  const owns = () =>
    useAuthStore.getState().user?.id === userId &&
    useOrgStore.getState().activeOrgId === data.organization_id;
  function select(scope: StartScope) {
    if (!canReviewStartScope(scopes, scope)) return;
    setReview(scope);
    setUrlParam("start-scope", scope);
    setUrlParam("start-step", null);
    setUrlParam("question", null);
  }
  function complete() {
    if (!current) return;
    state.saveScope.mutate(
      { scope: current, data: { completed: true } },
      {
        onSuccess: (saved) => {
          if (!owns()) return;
          setReview(saved.data.active_scope ?? null);
          setUrlParam("start-scope", saved.data.active_scope ?? null);
          setUrlParam("start-step", null);
          setUrlParam("question", null);
        },
      },
    );
  }
  const personal = scopes.find((scope) => scope.scope === "personal");
  const requestedPersonal =
    search.get("workspace") === data.organization_id
      ? personalStartStep(search.get("start-step"))
      : null;
  const resume =
    requestedPersonal ?? personalStartStep(personal?.current_step ?? data.current_step);
  const preferences =
    current === "personal" &&
    !preferencesDone &&
    (requestedPersonal?.startsWith("preferences.") ||
      (!data.completed && !resume?.startsWith("member.")));
  if (!userId || activeOrg?.id !== data.organization_id) return <StartSkeleton view="workspace" />;
  return (
    <StartScopeProvider
      value={{
        scopes,
        current: current ?? scopes.at(-1)?.scope ?? "personal",
        select,
        pending: state.saveScope.isPending || state.save.isPending,
        failed: state.saveScope.isError || state.save.isError,
        continueReview: reviewingComplete
          ? () => {
              setReview(required);
              setUrlParam("start-scope", required);
              setUrlParam("start-step", null);
              setUrlParam("question", null);
            }
          : undefined,
      }}
    >
      {children}
      {current === null ? (
        <div className={styles.shell}>
          <div className={styles.frame}>
            <StartScopeProgress />
            <h1 className="text-2xl font-semibold">{t("allDoneTitle")}</h1>
            <p className="text-muted-foreground mt-3">{t("allDoneHint")}</p>
            <Button asChild className="mt-6">
              <Link href="/chat">{t("openApp")}</Link>
            </Button>
          </div>
        </div>
      ) : current !== "personal" ? (
        <StartSharedJourney
          key={`${userId}:${data.organization_id}:${current}`}
          scope={current}
          org={activeOrg ?? undefined}
          organizations={organizations.data ?? []}
          currentStep={scopes.find((scope) => scope.scope === current)?.current_step ?? null}
          onSelect={switchOrg}
          onComplete={complete}
          pending={state.saveScope.isPending}
        />
      ) : preferences ? (
        <StartPreferences
          initialStage={resume === "preferences.appearance" ? "appearance" : "language"}
          continuing={state.save.isPending}
          onContinue={() =>
            state.save.mutate(
              { current_step: "member.welcome" },
              {
                onSuccess: () => {
                  if (owns()) {
                    setPreferencesDone(true);
                    rememberStartPosition("member.welcome", data.organization_id, "personal");
                  }
                },
              },
            )
          }
        />
      ) : (
        <StartMember key={`${userId}:${data.organization_id}`} data={data} resumeStep={resume} />
      )}
    </StartScopeProvider>
  );
}
