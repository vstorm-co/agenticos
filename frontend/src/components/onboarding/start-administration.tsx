"use client";
import { useReportStartStep } from "@/hooks/use-report-start-step";
import { useState, useEffect, useLayoutEffect, useRef } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { rememberStartPosition } from "./start-position";
import { ArrowUpRight } from "lucide-react";
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
import { StartSubscriptions } from "./start-subscriptions";
import { StartTasks } from "./start-tasks";
import { StartFinish } from "./start-finish";
import { StartActions, StartNavigation, StartNavigationScope } from "./start-navigation";
import { StartLanguage } from "./start-language";
import {
  useStartVariant,
  useStartTransition,
  StartVariantPicker,
  StartJourney,
} from "./start-experience";
import dynamic from "next/dynamic";
import { StartLaunch } from "./start-launch";
import styles from "./administration.module.css";
const StartModels = dynamic(
  () => import("./start-connections").then((module) => module.StartModels),
  {
    loading: () => <StartSkeleton fullPage={false} view="models" />,
  },
);
const StartTools = dynamic(
  () => import("./start-connections").then((module) => module.StartTools),
  {
    loading: () => <StartSkeleton fullPage={false} view="tools" />,
  },
);

const STEPS = [
  "workspace",
  "identity",
  "profile",
  "context",
  "subscriptions",
  "models",
  "tools",
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
  const [selectedOrgId, setSelectedOrgId] = useState<string | null>(activeOrg?.id ?? null);
  const org = activeOrg?.id === selectedOrgId ? activeOrg : null;
  const variant = useStartVariant();
  const experience = useTranslations("start.experience");
  const steps = STEPS.filter(
    (item) =>
      (appAdmin || item !== "deployment") && (variant || (item !== "models" && item !== "tools")),
  );
  const stepLabel = (id: Step) =>
    id === "models" || id === "tools" ? experience(`${id}Title`) : t(id);
  const search = useSearchParams();
  const requestedStep = steps.find((item) => `admin.${item}` === search.get("start-step"));
  const requestedWorkspace = requestedStep ? search.get("workspace") : null;
  const initialStep =
    activeOrg && requestedWorkspace === activeOrg.id ? (requestedStep ?? "workspace") : "workspace";
  const attemptedWorkspace = useRef<string | null>(null);
  const canResumeWorkspace = organizations.data?.some((item) => item.id === requestedWorkspace);
  useEffect(() => {
    if (
      !requestedWorkspace ||
      !canResumeWorkspace ||
      attemptedWorkspace.current === requestedWorkspace
    )
      return;
    attemptedWorkspace.current = requestedWorkspace;
    if (activeOrgId !== requestedWorkspace) switchOrg(requestedWorkspace);
  }, [activeOrgId, canResumeWorkspace, requestedWorkspace, switchOrg]);
  const [direction, setDirection] = useState<"forward" | "back">("forward");
  const [step, setStep] = useState<Step>(initialStep);
  useReportStartStep(`admin.${step}`, org?.id ?? null);
  const [visited, setVisited] = useState<readonly Step[]>(
    steps.slice(0, steps.indexOf(initialStep) + 1),
  );
  const content = useRef<HTMLDivElement>(null);
  const transition = useStartTransition(content, variant === "studio");
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
  const resuming =
    resumeChanged && initialStep !== "workspace" && step === "workspace" && visited.length === 1;
  if (resuming) {
    setSelectedOrgId(activeOrg?.id ?? null);
    setStep(initialStep);
    setVisited(steps.slice(0, steps.indexOf(initialStep) + 1));
  }
  const activeChanged = useChanged(activeOrgId);
  const scopeChanged = !resuming && activeChanged && selectedOrgId && activeOrgId !== selectedOrgId;
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
    const nextDirection = steps.indexOf(next) < index ? "back" : "forward";
    if (next !== step) transition(nextDirection);
    stepRef.current = next;
    rememberStartPosition(`admin.${next}`, scopeRef.current);
    setDirection(nextDirection);
    setStep(next);
    setVisited((previous) => (previous.includes(next) ? previous : [...previous, next]));
  };
  useEffect(() => {
    if (previousStep.current === step) return;
    previousStep.current = step;
    content.current
      ?.querySelector<HTMLElement>(":scope > section:not([hidden]) > h1")
      ?.focus({ preventScroll: true });
    if (variant === "studio" && content.current) content.current.scrollTop = 0;
    else
      content.current?.closest("main")?.scrollIntoView?.({ block: "start", behavior: "instant" });
  }, [step, variant]);
  const advance = (from: Step, next: Step) => {
    if (mounted.current && stepRef.current === from && scopeRef.current === org?.id) go(next);
  };
  const back = () =>
    go((variant ? visited[visited.indexOf(step) - 1] : steps[index - 1]) ?? "workspace");
  // A step asked as questions carries its own Back, which leaves the step from
  // its first question; a second one in the header would be the same control twice.
  const questionStep = step === "deployment" || step === "organization";
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
      <div className={styles.frame} data-start-frame data-direction={direction}>
        <nav className={styles.topbar} data-start-topbar aria-label={appName}>
          <Link href="/chat" className={styles.brand}>
            <BrandMark size={28} />
            {appName}
          </Link>
          <StartVariantPicker />
          <div className={styles.topActions}>
            <StartLanguage />
            <Link href="/chat">
              {t("openApp")}
              <ArrowUpRight size={15} aria-hidden />
            </Link>
          </div>
        </nav>
        <header className={styles.wizardHeader} data-start-header>
          <div className={styles.wizardMeta}>
            <div className={styles.wizardScope}>
              <span>{org?.name ?? t(appAdmin ? "applicationAdmin" : "organizationAdmin")}</span>
            </div>
            {variant !== "studio" && (
              <span>{t("stepPosition", { current: index + 1, total: steps.length })}</span>
            )}
          </div>
          <ol className={styles.progress} aria-label={t("steps")}>
            {steps.map((id, position) => (
              <li
                key={id}
                data-current={id === step}
                data-past={position < index}
                aria-current={id === step ? "step" : undefined}
              >
                <span className="sr-only">{stepLabel(id)}</span>
              </li>
            ))}
          </ol>
        </header>
        <StartJourney
          steps={steps}
          current={step}
          visited={visited}
          onSelect={go}
          label={stepLabel}
        />
        <StartNavigation onBack={index > 0 && !questionStep ? back : undefined}>
          <div ref={content} className={styles.content} data-start-content>
            {visited.includes("workspace") && (
              <section hidden={step !== "workspace"} aria-label={t("workspace")}>
                <h1 tabIndex={-1}>{t("workspaceTitle")}</h1>
                {variant === "studio" ? (
                  <StartGuide message={t("workspaceHint")} />
                ) : (
                  <>
                    <p className={styles.stageHint}>{t("workspaceHint")}</p>
                    <StartGuide message={guide("workspaceGuide")} />
                  </>
                )}
                {organizations.isPending ? (
                  <StartSkeleton fullPage={false} />
                ) : (
                  <StartNavigationScope active={step === "workspace"}>
                    <StartWorkspace
                      organizations={organizations.data ?? []}
                      activeOrgId={activeOrgId}
                      onSelect={select}
                    />
                  </StartNavigationScope>
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
                {variant === "studio" ? (
                  <StartGuide message={t("identityHint")} />
                ) : (
                  <>
                    <p className={styles.stageHint}>{t("identityHint")}</p>
                    <StartGuide message={guide("identityGuide")} />
                  </>
                )}
                <div className={styles.stageStudio} data-start-studio>
                  <StartNavigationScope active={step === "identity"}>
                    <OrganizationProfileSettings
                      org={org}
                      onContinue={() => advance("identity", "profile")}
                      saveLabel={t("saveContinue")}
                      renderActions={(actions) => <StartActions>{actions}</StartActions>}
                    />
                  </StartNavigationScope>
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
                {variant === "studio" ? (
                  <StartGuide message={t("identityProfileHint")} />
                ) : (
                  <>
                    <p className={styles.stageHint}>{t("identityProfileHint")}</p>
                    <StartGuide message={guide("profileGuide")} />
                  </>
                )}
                <div className={styles.stageStudio} data-start-studio>
                  <div className={styles.profileCard} data-start-profile>
                    <StartNavigationScope active={step === "profile"}>
                      <ProfileIdentitySettings
                        section="identity"
                        avatarPresentation={
                          variant === "studio" && step === "profile" ? "carousel" : "palette"
                        }
                        onContinue={() => advance("profile", "context")}
                        saveLabel={t("saveContinue")}
                        renderActions={(actions) => <StartActions>{actions}</StartActions>}
                      />
                    </StartNavigationScope>
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
                {variant === "studio" ? (
                  <StartGuide message={t("contextHint")} />
                ) : (
                  <>
                    <p className={styles.stageHint}>{t("contextHint")}</p>
                    <StartGuide message={guide("contextGuide")} />
                  </>
                )}
                <div className={styles.stageStudio} data-start-studio>
                  <div className={styles.profileCard} data-start-profile>
                    <StartNavigationScope active={step === "context"}>
                      <ProfileIdentitySettings
                        section="context"
                        onContinue={() => advance("context", "subscriptions")}
                        saveLabel={t("saveContinue")}
                        renderActions={(actions) => <StartActions>{actions}</StartActions>}
                        secondaryAction={
                          <Button variant="ghost" onClick={() => go("subscriptions")}>
                            {t("skipOptional")}
                          </Button>
                        }
                      />
                    </StartNavigationScope>
                  </div>
                  <StartStageArtwork stage="context" />
                </div>
              </section>
            )}
            {org && visited.includes("subscriptions") && (
              <section hidden={step !== "subscriptions"} aria-label={t("subscriptions")}>
                <h1 tabIndex={-1}>{t("subscriptions")}</h1>
                <StartGuide message={guide("subscriptionsGuide")} />
                <StartSubscriptions />
                <StartNavigationScope active={step === "subscriptions"}>
                  <StartActions>
                    <Button onClick={() => advance("subscriptions", variant ? "models" : "team")}>
                      {variant === "studio" ? experience("continue") : t("saveContinue")}
                    </Button>
                  </StartActions>
                </StartNavigationScope>
              </section>
            )}
            {org && variant && step === "models" && (
              <section aria-label={experience("modelsTitle")}>
                <h1 tabIndex={-1}>{experience("modelsTitle")}</h1>
                <StartGuide message={experience("modelsGuide")} />
                <StartModels />
                <StartActions>
                  <Button onClick={() => advance("models", "tools")}>
                    {variant === "studio" ? experience("continue") : t("saveContinue")}
                  </Button>
                </StartActions>
              </section>
            )}
            {org && variant && step === "tools" && (
              <section aria-label={experience("toolsTitle")}>
                <h1 tabIndex={-1}>{experience("toolsTitle")}</h1>
                <StartGuide message={experience("toolsGuide")} />
                <StartTools />
                <StartActions>
                  <Button variant="ghost" onClick={() => advance("tools", "task")}>
                    {experience("launchTitle")}
                  </Button>
                  <Button onClick={() => advance("tools", "team")}>{experience("continue")}</Button>
                </StartActions>
              </section>
            )}
            {org && visited.includes("team") && (
              <section key={`team-${org.id}`} hidden={step !== "team"} aria-label={t("team")}>
                <h1 tabIndex={-1}>{t("teamTitle")}</h1>
                <p className={styles.stageHint}>{t("teamHint")}</p>
                {variant !== "studio" && <StartGuide message={guide("teamGuide")} />}
                <div className={styles.stageStudio} data-start-studio>
                  <StartNavigationScope active={step === "team"}>
                    <StartInviteTeam
                      org={org}
                      onContinue={() => advance("team", appAdmin ? "deployment" : "organization")}
                    />
                  </StartNavigationScope>
                  <StartStageArtwork stage="team" />
                </div>
              </section>
            )}
            {org && appAdmin && visited.includes("deployment") && (
              <section hidden={step !== "deployment"} aria-label={t("deployment")}>
                <h1 className="sr-only" tabIndex={-1}>
                  {t("deploymentTitle")}
                </h1>
                <StartNavigationScope active={step === "deployment"}>
                  <StartDeployment
                    active={step === "deployment"}
                    org={org}
                    onBack={back}
                    onContinue={() => advance("deployment", "organization")}
                  />
                </StartNavigationScope>
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
                <StartNavigationScope active={step === "organization"}>
                  <StartOrganizationSettings
                    active={step === "organization"}
                    org={org}
                    onBack={back}
                    onContinue={() => advance("organization", "task")}
                  />
                </StartNavigationScope>
              </section>
            )}
            {org && step === "task" && (
              <section key={`task-${org.id}`} aria-label={t("task")}>
                <h1 tabIndex={-1}>{variant ? experience("launchTitle") : t("taskTitle")}</h1>
                {!variant && <p className={styles.stageHint}>{t("taskHint")}</p>}
                <StartGuide message={variant ? experience("launchGuide") : guide("taskGuide")} />
                <AdminFirstTask orgId={org.id} />
              </section>
            )}
          </div>
        </StartNavigation>
      </div>
    </div>
  );
}
function AdminFirstTask({ orgId }: { orgId: string }) {
  const t = useTranslations("start");
  const state = useStart();
  const useVariant = useStartVariant();
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
      {useVariant ? <StartLaunch data={state.data} /> : <StartTasks data={state.data} />}
      <StartFinish />
    </div>
  );
}
