"use client";
import { useReportStartStep } from "@/hooks/use-report-start-step";

import { useState, useRef, useEffect, useLayoutEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useAuthStore } from "@/stores/auth-store";
import { useBranding } from "@/components/branding/branding-provider";
import { BrandMark } from "@/components/branding/brand-mark";
import { AvatarFace } from "@/components/ui/avatar-face";
import { Button } from "@/components/ui";
import { ProfileIdentitySettings } from "@/components/settings/profile-identity-settings";
import type { Onboarding } from "@/lib/onboarding-api";
import { StartActions, StartNavigation, StartNavigationScope } from "./start-navigation";
import { StartLanguage } from "./start-language";
import { StartCompanions } from "./start-companions";
import { StartGuide } from "./start-guide";
import { StartStageArtwork } from "./start-stage-artwork";
import { StartSubscriptions } from "./start-subscriptions";
import { StartTasks } from "./start-tasks";
import { StartFinish } from "./start-finish";
import { rememberStartPosition } from "./start-position";
import {
  useStartVariant,
  useStartTransition,
  StartVariantPicker,
  StartJourney,
} from "./start-experience";
import dynamic from "next/dynamic";
import { StartSkeleton } from "./start-skeleton";
import { StartLaunch } from "./start-launch";
import styles from "./administration.module.css";
import guided from "./guided-start.module.css";

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
  "welcome",
  "profile",
  "context",
  "subscriptions",
  "models",
  "tools",
  "task",
] as const;
type Step = (typeof STEPS)[number];

/** Members prepare their own profile and first task, never deployment or team policy. */
export function StartMember({ data }: { data: Onboarding }) {
  const t = useTranslations("start.guided");
  const admin = useTranslations("start.administration");
  const { appName } = useBranding();
  const user = useAuthStore((state) => state.user);
  const search = useSearchParams();
  const variant = useStartVariant();
  const experience = useTranslations("start.experience");
  const steps = STEPS.filter((item) => variant || (item !== "models" && item !== "tools"));
  const stepLabel = (id: Step) =>
    id === "models" || id === "tools" ? experience(`${id}Title`) : t(`memberStep.${id}`);
  const initial =
    search.get("workspace") === data.organization_id
      ? steps.find((item) => `member.${item}` === search.get("start-step"))
      : undefined;
  const [step, setStep] = useState<Step>(initial ?? "welcome");
  useReportStartStep(`member.${step}`, data.organization_id, !data.completed);
  const [direction, setDirection] = useState<"forward" | "back">("forward");
  const [visited, setVisited] = useState<readonly Step[]>(
    steps.slice(0, steps.indexOf(initial ?? "welcome") + 1),
  );
  const current = useRef(step);
  const mounted = useRef(true);
  const content = useRef<HTMLDivElement>(null);
  const transition = useStartTransition(content, variant === "studio");
  useEffect(() => {
    content.current
      ?.querySelector<HTMLElement>("section:not([hidden]) h1")
      ?.focus({ preventScroll: true });
    if (variant === "studio" && content.current) content.current.scrollTop = 0;
    else
      content.current?.closest("main")?.scrollIntoView?.({ block: "start", behavior: "instant" });
  }, [step, variant]);
  useLayoutEffect(() => {
    current.current = step;
  }, [step]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const index = steps.indexOf(step);
  const knownProfile =
    search.get("entry") === "joined" ||
    !!(user?.avatar_url || user?.job_title || user?.about || user?.onboarding_completed_at);
  const go = (next: Step) => {
    const nextDirection = steps.indexOf(next) < index ? "back" : "forward";
    if (next !== step) transition(nextDirection);
    setDirection(nextDirection);
    current.current = next;
    setStep(next);
    setVisited((old) => (old.includes(next) ? old : [...old, next]));
    rememberStartPosition(`member.${next}`, data.organization_id);
  };
  const advance = (from: Step, next: Step) => {
    if (mounted.current && current.current === from) go(next);
  };
  return (
    <div className={styles.shell}>
      <div className={styles.frame} data-start-frame data-direction={direction}>
        <nav className={styles.topbar} data-start-topbar aria-label={appName}>
          <Link className={styles.brand} href="/chat">
            <BrandMark size={28} />
            {appName}
          </Link>
          <StartVariantPicker />
          <div className={styles.topActions}>
            <StartLanguage />
            <Link href="/chat">
              {admin("openApp")}
              <ArrowUpRight size={15} aria-hidden />
            </Link>
          </div>
        </nav>
        <header className={styles.wizardHeader} data-start-header>
          <div className={styles.wizardMeta}>
            <div className={styles.wizardScope}>
              <span>{data.organization_name}</span>
            </div>
            {variant !== "studio" && (
              <span>{admin("stepPosition", { current: index + 1, total: steps.length })}</span>
            )}
          </div>
          <ol className={styles.progress} aria-label={admin("steps")}>
            {steps.map((item, position) => (
              <li
                key={item}
                data-current={item === step}
                data-past={position < index}
                aria-current={item === step ? "step" : undefined}
              >
                <span className="sr-only">{stepLabel(item)}</span>
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
        <StartNavigation onBack={index > 0 ? () => go(steps[index - 1] ?? "welcome") : undefined}>
          <div ref={content} className={styles.content} data-start-content>
            {step === "welcome" && (
              <div className={guided.journey}>
                {variant !== "studio" && (
                  <StartGuide
                    message={t(knownProfile ? "memberReturningGuide" : "memberNewGuide")}
                  />
                )}
                <section
                  className={`${guided.question} ${guided.memberWelcome}`}
                  data-start-welcome
                >
                  {variant !== "studio" && (
                    <div className={guided.memberMark}>
                      <span>
                        <AvatarFace seed="agenticos" />
                      </span>
                      {variant ? (
                        <span>
                          <AvatarFace seed="architect" />
                        </span>
                      ) : (
                        <StartCompanions members={["pebble", "mochi", "byte"]} />
                      )}
                    </div>
                  )}
                  <h1 tabIndex={-1}>{t("memberWelcome", { workspace: data.organization_name })}</h1>
                  {variant === "studio" ? (
                    <StartGuide
                      message={t(knownProfile ? "memberExistingProfile" : "memberWelcomeBody")}
                    />
                  ) : (
                    <p>{t(knownProfile ? "memberExistingProfile" : "memberWelcomeBody")}</p>
                  )}
                  <StartActions>
                    {knownProfile && (
                      <Button variant="ghost" onClick={() => go("profile")}>
                        {t("reviewProfile")}
                      </Button>
                    )}
                    <Button onClick={() => go(knownProfile ? "subscriptions" : "profile")}>
                      {t(knownProfile ? "useSavedProfile" : "letsGo")}
                      <ArrowRight size={16} aria-hidden />
                    </Button>
                  </StartActions>
                </section>
              </div>
            )}
            {(["profile", "context"] as const).map(
              (item) =>
                visited.includes(item) && (
                  <section key={item} hidden={step !== item} aria-label={t(`memberStep.${item}`)}>
                    <h1 tabIndex={-1}>
                      {admin(item === "profile" ? "identityProfileTitle" : "contextTitle")}
                    </h1>
                    <StartGuide message={t(item === "profile" ? "profileGuide" : "contextGuide")} />
                    <div className={styles.stageStudio} data-start-studio>
                      <div className={styles.profileCard} data-start-profile>
                        <StartNavigationScope active={step === item}>
                          <ProfileIdentitySettings
                            section={item === "profile" ? "identity" : "context"}
                            avatarPresentation={
                              variant === "studio" && step === item ? "carousel" : "palette"
                            }
                            saveLabel={admin("saveContinue")}
                            renderActions={(actions) => <StartActions>{actions}</StartActions>}
                            onContinue={() =>
                              advance(item, item === "profile" ? "context" : "subscriptions")
                            }
                            secondaryAction={
                              item === "context" && (
                                <Button variant="ghost" onClick={() => go("subscriptions")}>
                                  {admin("skipOptional")}
                                </Button>
                              )
                            }
                          />
                        </StartNavigationScope>
                      </div>
                      <StartStageArtwork stage={item} />
                    </div>
                  </section>
                ),
            )}
            {step === "subscriptions" && (
              <section aria-label={t("memberStep.subscriptions")}>
                <h1 tabIndex={-1}>{admin("subscriptions")}</h1>
                <StartGuide message={t("subscriptionsGuide")} />
                <StartSubscriptions />
                <StartActions>
                  <Button onClick={() => advance("subscriptions", variant ? "models" : "task")}>
                    {variant === "studio" ? experience("continue") : admin("saveContinue")}
                  </Button>
                </StartActions>
              </section>
            )}
            {variant && step === "models" && (
              <section aria-label={experience("modelsTitle")}>
                <h1 tabIndex={-1}>{experience("modelsTitle")}</h1>
                <StartGuide message={experience("modelsGuide")} />
                <StartModels />
                <StartActions>
                  <Button onClick={() => advance("models", "tools")}>
                    {variant === "studio" ? experience("continue") : admin("saveContinue")}
                  </Button>
                </StartActions>
              </section>
            )}
            {variant && step === "tools" && (
              <section aria-label={experience("toolsTitle")}>
                <h1 tabIndex={-1}>{experience("toolsTitle")}</h1>
                <StartGuide message={experience("toolsGuide")} />
                <StartTools />
                <StartActions>
                  <Button onClick={() => advance("tools", "task")}>
                    {variant === "studio" ? experience("continue") : admin("saveContinue")}
                  </Button>
                </StartActions>
              </section>
            )}
            {step === "task" && (
              <section aria-label={t("memberStep.task")}>
                <h1 tabIndex={-1}>{variant ? experience("launchTitle") : admin("taskTitle")}</h1>
                <StartGuide message={variant ? experience("launchGuide") : t("taskGuide")} />
                {variant ? <StartLaunch data={data} /> : <StartTasks data={data} />}
                <StartFinish />
              </section>
            )}
          </div>
        </StartNavigation>
      </div>
    </div>
  );
}
