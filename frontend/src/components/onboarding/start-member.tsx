"use client";

import { useState, useRef, useEffect, useLayoutEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, ArrowRight, ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useAuthStore } from "@/stores/auth-store";
import { useBranding } from "@/components/branding/branding-provider";
import { BrandMark } from "@/components/branding/brand-mark";
import { AvatarFace } from "@/components/ui/avatar-face";
import { Button } from "@/components/ui";
import { ProfileIdentitySettings } from "@/components/settings/profile-identity-settings";
import type { Onboarding } from "@/lib/onboarding-api";
import { StartLanguage } from "./start-language";
import { StartTour } from "./start-tour";
import { StartCompanions } from "./start-companions";
import { StartGuide } from "./start-guide";
import { StartStageArtwork } from "./start-stage-artwork";
import { StartTasks } from "./start-tasks";
import { StartFinish } from "./start-finish";
import { rememberStartPosition } from "./start-position";
import styles from "./administration.module.css";
import guided from "./guided-start.module.css";

const STEPS = ["welcome", "profile", "context", "task"] as const;
type Step = (typeof STEPS)[number];

/** Members prepare their own profile and first task, never deployment or team policy. */
export function StartMember({ data }: { data: Onboarding }) {
  const t = useTranslations("start.guided");
  const admin = useTranslations("start.administration");
  const { appName } = useBranding();
  const user = useAuthStore((state) => state.user);
  const search = useSearchParams();
  const initial =
    search.get("workspace") === data.organization_id
      ? STEPS.find((item) => `member.${item}` === search.get("start-step"))
      : undefined;
  const [step, setStep] = useState<Step>(initial ?? "welcome");
  const [visited, setVisited] = useState<readonly Step[]>(
    STEPS.slice(0, STEPS.indexOf(initial ?? "welcome") + 1),
  );
  const current = useRef(step);
  const mounted = useRef(true);
  const content = useRef<HTMLDivElement>(null);
  useEffect(() => {
    content.current
      ?.querySelector<HTMLElement>("section:not([hidden]) h1")
      ?.focus({ preventScroll: true });
    content.current?.closest("main")?.scrollIntoView?.({ block: "start", behavior: "instant" });
  }, [step]);
  useLayoutEffect(() => {
    current.current = step;
  }, [step]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const index = STEPS.indexOf(step);
  const knownProfile =
    search.get("entry") === "joined" ||
    !!(user?.avatar_url || user?.job_title || user?.about || user?.onboarding_completed_at);
  const go = (next: Step) => {
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
      <div className={styles.frame}>
        <nav className={styles.topbar} aria-label={appName}>
          <Link className={styles.brand} href="/chat">
            <BrandMark size={28} />
            {appName}
          </Link>
          <div className={styles.topActions}>
            <StartLanguage />
            <Link href="/chat">
              {admin("openApp")}
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
                  onClick={() => go(STEPS[index - 1] ?? "welcome")}
                >
                  <ArrowLeft size={14} aria-hidden />
                  {t("back")}
                </button>
              )}
              <span>{data.organization_name}</span>
            </div>
            <span>{admin("stepPosition", { current: index + 1, total: STEPS.length })}</span>
          </div>
          <ol className={styles.progress} aria-label={admin("steps")}>
            {STEPS.map((item, position) => (
              <li
                key={item}
                data-current={item === step}
                data-past={position < index}
                aria-current={item === step ? "step" : undefined}
              >
                <span className="sr-only">{t(`memberStep.${item}`)}</span>
              </li>
            ))}
          </ol>
        </header>
        <div ref={content} className={styles.content}>
          {step === "welcome" && (
            <div className={guided.journey}>
              <StartGuide message={t(knownProfile ? "memberReturningGuide" : "memberNewGuide")} />
              <section className={`${guided.question} ${guided.memberWelcome}`}>
                <div className={guided.memberMark}>
                  <span>
                    <AvatarFace seed="agenticos" />
                  </span>
                  <StartCompanions members={["pebble", "mochi", "byte"]} />
                </div>
                <h1 tabIndex={-1}>{t("memberWelcome", { workspace: data.organization_name })}</h1>
                <p>{t(knownProfile ? "memberExistingProfile" : "memberWelcomeBody")}</p>
                <Button onClick={() => go(knownProfile ? "task" : "profile")}>
                  {t(knownProfile ? "useSavedProfile" : "letsGo")}
                  <ArrowRight size={16} aria-hidden />
                </Button>
                {knownProfile && (
                  <Button variant="ghost" onClick={() => go("profile")}>
                    {t("reviewProfile")}
                  </Button>
                )}
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
                  <div className={styles.stageStudio}>
                    <div className={styles.profileCard}>
                      <ProfileIdentitySettings
                        section={item === "profile" ? "identity" : "context"}
                        saveLabel={admin("saveContinue")}
                        onContinue={() => advance(item, item === "profile" ? "context" : "task")}
                        secondaryAction={
                          <Button
                            variant="ghost"
                            onClick={() => go(item === "profile" ? "context" : "task")}
                          >
                            {admin("skipOptional")}
                          </Button>
                        }
                      />
                    </div>
                    <StartStageArtwork stage={item} />
                  </div>
                </section>
              ),
          )}
          {step === "task" && (
            <section aria-label={t("memberStep.task")}>
              <h1 tabIndex={-1}>{admin("taskTitle")}</h1>
              <StartGuide message={t("taskGuide")} />
              <StartTasks data={data} />
              <StartFinish />
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
