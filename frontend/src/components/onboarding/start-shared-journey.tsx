"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowUpRight } from "lucide-react";
import { BrandMark } from "@/components/branding/brand-mark";
import { useBranding } from "@/components/branding/branding-provider";
import { useReportStartStep } from "@/hooks/use-report-start-step";
import { ORGANIZATION_STEPS } from "@/lib/onboarding/scopes";
import type { StartScope } from "@/lib/onboarding-api";
import type { Organization } from "@/types";
import { StartLanguage } from "./start-language";
import { StartScopeProgress } from "./start-scope-progress";
import { StartNavigation, StartNavigationScope } from "./start-navigation";
import { StartJourney } from "./start-experience";
import { StartSharedStage, type SharedStartStep } from "./start-shared-stage";
import { rememberStartPosition } from "./start-position";
import styles from "./administration.module.css";
import { setUrlParam } from "@/lib/utils";

export function StartSharedJourney({
  scope,
  org,
  organizations,
  currentStep,
  onSelect,
  onComplete,
  pending,
}: {
  scope: Exclude<StartScope, "personal">;
  org?: Organization;
  organizations: Organization[];
  currentStep: string | null;
  onSelect: (id: string) => void;
  onComplete: () => void;
  pending: boolean;
}) {
  const t = useTranslations("start.administration");
  const experience = useTranslations("start.experience");
  const { appName } = useBranding();
  const search = useSearchParams();
  const steps: readonly SharedStartStep[] =
    scope === "deployment" ? ["deployment"] : ORGANIZATION_STEPS;
  const requested = search.get("start-step");
  const initial =
    steps.find((step) => `admin.${step}` === requested) ??
    steps.find((step) => `admin.${step}` === currentStep) ??
    steps[0]!;
  const [step, setStep] = useState(initial);
  const [visited, setVisited] = useState<readonly SharedStartStep[]>(
    steps.slice(0, steps.indexOf(initial) + 1),
  );
  const current = useRef(step);
  const mounted = useRef(true);
  const content = useRef<HTMLFieldSetElement>(null);
  const index = steps.indexOf(step);
  const organizationId = org?.id ?? null;
  useReportStartStep(`admin.${step}`, organizationId, true, scope);
  const routeStep = search.get("start-step");
  const routeOrganization = search.get("workspace");
  const routeScope = search.get("start-scope");
  useLayoutEffect(() => {
    if (routeStep !== `admin.${step}` || routeOrganization !== organizationId)
      rememberStartPosition(`admin.${step}`, organizationId, scope);
    else if (routeScope !== scope) setUrlParam("start-scope", scope);
  }, [step, organizationId, scope, routeStep, routeOrganization, routeScope]);
  useLayoutEffect(() => {
    current.current = step;
  }, [step]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    content.current
      ?.querySelector<HTMLElement>("section:not([hidden]) h1")
      ?.focus({ preventScroll: true });
  }, [step]);
  function go(next: SharedStartStep) {
    if (!mounted.current || pending) return;
    current.current = next;
    setStep(next);
    setVisited((old) => (old.includes(next) ? old : [...old, next]));
    rememberStartPosition(`admin.${next}`, organizationId, scope);
  }
  function advance(from: SharedStartStep) {
    if (!mounted.current || pending || current.current !== from) return;
    const next = steps[steps.indexOf(from) + 1];
    if (next) go(next);
    else onComplete();
  }
  const label = (id: SharedStartStep) =>
    id === "models" || id === "tools" ? experience(`${id}Title`) : t(id);
  return (
    <div className={styles.shell}>
      <div
        className={styles.frame}
        data-start-frame
        data-start-single={steps.length === 1 ? "" : undefined}
      >
        <nav className={styles.topbar} data-start-topbar aria-label={appName}>
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
        <header className={styles.wizardHeader} data-start-header>
          <StartScopeProgress />
        </header>
        {steps.length > 1 && (
          <StartJourney
            steps={steps}
            current={step}
            visited={visited}
            onSelect={go}
            label={label}
          />
        )}
        <StartNavigation
          pending={pending}
          onBack={index > 0 && step !== "organization" ? () => go(steps[index - 1]!) : undefined}
        >
          <fieldset
            ref={content}
            disabled={pending}
            className={`${styles.content} min-w-0 border-0 p-0`}
            data-start-content
          >
            {visited.map((id) => (
              <section key={id} hidden={id !== step} aria-label={label(id)}>
                <h1
                  tabIndex={-1}
                  className={id === "deployment" || id === "organization" ? "sr-only" : undefined}
                >
                  {label(id)}
                </h1>
                <StartNavigationScope active={id === step}>
                  <StartSharedStage
                    step={id}
                    active={id === step}
                    org={org}
                    organizations={organizations}
                    onSelect={(selected) => {
                      if (mounted.current && !pending && current.current === "workspace") {
                        onSelect(selected);
                        if (selected === organizationId) advance("workspace");
                      }
                    }}
                    onNext={() => advance(id)}
                    onBack={index > 0 ? () => go(steps[index - 1]!) : undefined}
                  />
                </StartNavigationScope>
              </section>
            ))}
          </fieldset>
        </StartNavigation>
      </div>
    </div>
  );
}
