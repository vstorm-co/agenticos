"use client";
import { useState, useEffect, useLayoutEffect, useRef } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { rememberStartPosition } from "./start-position";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { BrandMark } from "@/components/branding/brand-mark";
import { useBranding } from "@/components/branding/branding-provider";
import { useOrganizations, useOrganizationList } from "@/hooks/use-organizations";
import { useChanged } from "@/hooks/use-changed";
import { useStart } from "@/hooks/use-start";
import { ErrorState } from "@/components/states";
import { ProfileIdentitySettings } from "@/components/settings/profile-identity-settings";
import { OrganizationProfileSettings } from "@/components/teams/organization-profile-settings";
import { StartDeployment } from "./start-deployment";
import { StartGuide } from "./start-guide";
import { StartStageArtwork } from "./start-stage-artwork";
import { StartSkeleton } from "./start-skeleton";
import { StartWorkspace } from "./start-workspace";
import { StartInviteTeam } from "./start-invite-team";
import { StartOrganizationSettings } from "./start-organization-settings";
import { StartTasks } from "./start-tasks";
import { StartFinish } from "./start-finish";
import { StartLanguage } from "./start-language";
import { StartTour } from "./start-tour";
import styles from "./administration.module.css";
const STEPS = [
  "workspace",
  "identity",
  "profile",
  "context",
  "team",
  "deployment",
  "organization",
  "task",
] as const;
type Step = (typeof STEPS)[number];

export function StartAdministration({ appAdmin }: { appAdmin: boolean }) {
  const t = useTranslations("start.administration");
  const guide = useTranslations("start.guided");
  const { appName } = useBranding();
  const { activeOrg, activeOrgId, switchOrg } = useOrganizations();
  const organizations = useOrganizationList();
  const [selectedOrgId, setSelectedOrgId] = useState<string | null>(
    activeOrg && !activeOrg.is_personal ? activeOrg.id : null,
  );
  const org = activeOrg?.id === selectedOrgId ? activeOrg : null;
  const steps = STEPS.filter((item) => appAdmin || item !== "deployment");
  const search = useSearchParams();
  const initialStep =
    activeOrg && !activeOrg.is_personal && search.get("workspace") === activeOrg.id
      ? (steps.find((item) => `admin.${item}` === search.get("start-step")) ?? "workspace")
      : "workspace";
  const [direction, setDirection] = useState<"forward" | "back">("forward");
  const [step, setStep] = useState<Step>(initialStep);
  const [visited, setVisited] = useState<readonly Step[]>(
    steps.slice(0, steps.indexOf(initialStep) + 1),
  );
  const content = useRef<HTMLDivElement>(null);
  const previousStep = useRef(step);
  const index = steps.indexOf(step);
  const stepRef = useRef<Step>(step);
  const scopeRef = useRef(selectedOrgId);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const resumeChanged = useChanged(`${activeOrg?.id}|${initialStep}`);
  if (
    resumeChanged &&
    initialStep !== "workspace" &&
    step === "workspace" &&
    visited.length === 1
  ) {
    setSelectedOrgId(activeOrg?.id ?? null);
    setStep(initialStep);
    setVisited(steps.slice(0, steps.indexOf(initialStep) + 1));
  }
  const scopeChanged = useChanged(activeOrgId) && selectedOrgId && activeOrgId !== selectedOrgId;
  if (scopeChanged || !steps.includes(step)) {
    if (scopeChanged) setSelectedOrgId(null);
    setStep("workspace");
    setVisited(["workspace"]);
  }
  useLayoutEffect(() => {
    stepRef.current = step;
    scopeRef.current = selectedOrgId;
  }, [step, selectedOrgId]);
  const go = (next: Step) => {
    stepRef.current = next;
    rememberStartPosition(`admin.${next}`, scopeRef.current);
    setDirection(steps.indexOf(next) < index ? "back" : "forward");
    setStep(next);
    setVisited((previous) => (previous.includes(next) ? previous : [...previous, next]));
  };
  useEffect(() => {
    if (previousStep.current === step) return;
    previousStep.current = step;
    content.current
      ?.querySelector<HTMLElement>(":scope > section:not([hidden]) > h1")
      ?.focus({ preventScroll: true });
    content.current?.closest("main")?.scrollIntoView?.({ block: "start", behavior: "instant" });
  }, [step]);
  const advance = (from: Step, next: Step) => {
    if (mounted.current && stepRef.current === from && scopeRef.current === org?.id) go(next);
  };
  const select = (id: string) => {
    if (!mounted.current || stepRef.current !== "workspace") return;
    switchOrg(id);
    setSelectedOrgId(id);
    scopeRef.current = id;
    go("identity");
  };
  if (organizations.error)
    return (
      <ErrorState
        title={t("loadFailed")}
        cta={{ label: t("retry"), onClick: () => void organizations.refetch() }}
      />
    );
  return (
    <div className={styles.shell}>
      <div
        className={styles.frame}
        data-direction={direction}
        data-focused={step === "deployment" || step === "organization"}
      >
        <nav className={styles.topbar} aria-label={appName}>
          <Link href="/chat" className={styles.brand}>
            <BrandMark size={28} />
            {appName}
          </Link>
          <div className={styles.topActions}>
            <StartLanguage />
            <Link href="/chat">
              {t("openApp")}
              <ArrowUpRight size={15} aria-hidden />
            </Link>
          </div>
        </nav>
        <header className={styles.wizardHeader}>
          <div className={styles.wizardMeta}>
            <div className={styles.wizardScope}>
              {index > 0 && (
                <button
                  className={styles.wizardBack}
                  type="button"
                  onClick={() => go(steps[index - 1] ?? "workspace")}
                >
                  <ArrowLeft size={14} aria-hidden />
                  {t("backStep")}
                </button>
              )}
              <span>{org?.name ?? t(appAdmin ? "applicationAdmin" : "organizationAdmin")}</span>
            </div>
            <span>{t("stepPosition", { current: index + 1, total: steps.length })}</span>
          </div>
          <ol className={styles.progress} aria-label={t("steps")}>
            {steps.map((id, position) => (
              <li
                key={id}
                data-current={id === step}
                data-past={position < index}
                aria-current={id === step ? "step" : undefined}
              >
                <span className="sr-only">{t(id)}</span>
              </li>
            ))}
          </ol>
        </header>
        <div ref={content} className={styles.content}>
          {visited.includes("workspace") && (
            <section hidden={step !== "workspace"} aria-label={t("workspace")}>
              <h1 tabIndex={-1}>{t("workspaceTitle")}</h1>
              <p className={styles.stageHint}>{t("workspaceHint")}</p>
              <StartGuide message={guide("workspaceGuide")} />
              {organizations.isPending ? (
                <StartSkeleton fullPage={false} />
              ) : (
                <StartWorkspace
                  organizations={organizations.data ?? []}
                  activeOrgId={activeOrgId}
                  onSelect={select}
                />
              )}
            </section>
          )}
          {org && visited.includes("identity") && (
            <section
              key={`identity-${org.id}`}
              hidden={step !== "identity"}
              aria-label={t("identity")}
            >
              <h1 tabIndex={-1}>{t("identityTitle")}</h1>
              <p className={styles.stageHint}>{t("identityHint")}</p>
              <StartGuide message={guide("identityGuide")} />
              <div className={styles.stageStudio}>
                <OrganizationProfileSettings
                  org={org}
                  onContinue={() => advance("identity", "profile")}
                  saveLabel={t("saveContinue")}
                />
                <StartStageArtwork stage="identity" />
              </div>
            </section>
          )}
          {org && visited.includes("profile") && (
            <section
              key={`profile-${org.id}`}
              hidden={step !== "profile"}
              aria-label={t("profile")}
            >
              <h1 tabIndex={-1}>{t("identityProfileTitle")}</h1>
              <p className={styles.stageHint}>{t("identityProfileHint")}</p>
              <StartGuide message={guide("profileGuide")} />
              <div className={styles.stageStudio}>
                <div className={styles.profileCard}>
                  <ProfileIdentitySettings
                    section="identity"
                    onContinue={() => advance("profile", "context")}
                    saveLabel={t("saveContinue")}
                    secondaryAction={
                      <Button variant="ghost" onClick={() => go("context")}>
                        {t("skipOptional")}
                      </Button>
                    }
                  />
                </div>
                <StartStageArtwork stage="profile" />
              </div>
            </section>
          )}
          {org && visited.includes("context") && (
            <section
              key={`context-${org.id}`}
              hidden={step !== "context"}
              aria-label={t("context")}
            >
              <h1 tabIndex={-1}>{t("contextTitle")}</h1>
              <p className={styles.stageHint}>{t("contextHint")}</p>
              <StartGuide message={guide("contextGuide")} />
              <div className={styles.stageStudio}>
                <div className={styles.profileCard}>
                  <ProfileIdentitySettings
                    section="context"
                    onContinue={() => advance("context", "team")}
                    saveLabel={t("saveContinue")}
                    secondaryAction={
                      <Button variant="ghost" onClick={() => go("team")}>
                        {t("skipOptional")}
                      </Button>
                    }
                  />
                </div>
                <StartStageArtwork stage="context" />
              </div>
            </section>
          )}
          {org && visited.includes("team") && (
            <section key={`team-${org.id}`} hidden={step !== "team"} aria-label={t("team")}>
              <h1 tabIndex={-1}>{t("teamTitle")}</h1>
              <p className={styles.stageHint}>{t("teamHint")}</p>
              <StartGuide message={guide("teamGuide")} />
              <div className={styles.stageStudio}>
                <StartInviteTeam
                  org={org}
                  onContinue={() => advance("team", appAdmin ? "deployment" : "organization")}
                />
                <StartStageArtwork stage="team" />
              </div>
            </section>
          )}
          {org && appAdmin && visited.includes("deployment") && (
            <section hidden={step !== "deployment"} aria-label={t("deployment")}>
              <h1 className="sr-only" tabIndex={-1}>
                {t("deploymentTitle")}
              </h1>
              <StartDeployment
                active={step === "deployment"}
                org={org}
                onContinue={() => advance("deployment", "organization")}
              />
            </section>
          )}
          {org && visited.includes("organization") && (
            <section
              key={`settings-${org.id}`}
              hidden={step !== "organization"}
              aria-label={t("organization")}
            >
              <h1 className="sr-only" tabIndex={-1}>
                {t("organizationTitle", { workspace: org.name })}
              </h1>
              <StartOrganizationSettings
                active={step === "organization"}
                org={org}
                onContinue={() => advance("organization", "task")}
              />
            </section>
          )}
          {org && step === "task" && (
            <section key={`task-${org.id}`} aria-label={t("task")}>
              <h1 tabIndex={-1}>{t("taskTitle")}</h1>
              <p className={styles.stageHint}>{t("taskHint")}</p>
              <StartGuide message={guide("taskGuide")} />
              <AdminFirstTask orgId={org.id} />
            </section>
          )}
        </div>
        <footer className="mt-6 flex justify-end">
          <StartTour />
        </footer>
      </div>
    </div>
  );
}
function AdminFirstTask({ orgId }: { orgId: string }) {
  const t = useTranslations("start");
  const state = useStart();
  if (state.error)
    return (
      <ErrorState
        title={t("loadFailed")}
        cta={{ label: t("retry"), onClick: () => void state.refetch() }}
      />
    );
  if (!state.data || state.data.organization_id !== orgId)
    return <StartSkeleton fullPage={false} view="tasks" />;
  return (
    <div className="space-y-6">
      <StartTasks data={state.data} />
      <StartFinish />
    </div>
  );
}
