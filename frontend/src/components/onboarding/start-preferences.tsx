"use client";
import { useReportStartStep } from "@/hooks/use-report-start-step";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, ArrowUpRight, Check } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { BrandMark } from "@/components/branding/brand-mark";
import { useBranding } from "@/components/branding/branding-provider";
import { Button } from "@/components/ui";
import { useOrgStore } from "@/stores/org-store";
import { useChooseLocale } from "@/hooks/use-choose-locale";
import { getLocaleFlag, getLocaleLabel } from "@/i18n";
import { locales, type Locale } from "@/lib/locales";
import { useStartTransition } from "./start-experience";
import { StartPreferencesAppearance } from "./start-preferences-appearance";
import styles from "./start-preferences.module.css";

/** Deliberate account preferences precede workspace setup; merely visiting saves nothing. */
export function StartPreferences({
  onContinue,
  children,
}: {
  onContinue: () => void;
  children?: ReactNode;
}) {
  const t = useTranslations("start.preferences");
  const navigation = useTranslations("start.administration");
  const guided = useTranslations("start.guided");
  const locale = useLocale();
  const chooseLocale = useChooseLocale();
  const { appName } = useBranding();
  const [stage, setStage] = useState<"language" | "appearance">("language");
  const organizationId = useOrgStore((state) => state.activeOrgId);
  useReportStartStep(`preferences.${stage}`, organizationId);
  const [chosenLocale, setChosenLocale] = useState<Locale | null>(null);
  const content = useRef<HTMLElement>(null);
  const transition = useStartTransition(content, true);
  function changeStage(next: "language" | "appearance") {
    if (next !== stage) transition(next === "appearance" ? "forward" : "back");
    setStage(next);
  }
  const titleId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, [stage]);
  return (
    <div className={styles.shell} data-start-preferences={stage}>
      <nav className={styles.topbar} aria-label={appName}>
        <Link href="/chat" className={styles.brand}>
          <BrandMark size={28} />
          <span>{appName}</span>
        </Link>
        <Link href="/chat" className={styles.openApp}>
          {navigation("openApp")}
          <ArrowUpRight className="size-4" aria-hidden />
        </Link>
      </nav>
      <div className={styles.viewport}>
        <section ref={content} className={styles.content} aria-labelledby={titleId}>
          {children}
          <header className={styles.question}>
            <h1 id={titleId} ref={heading} tabIndex={-1}>
              {t(stage === "language" ? "languageTitle" : "appearanceTitle")}
            </h1>
            <p>{t(stage === "language" ? "languageHint" : "appearanceHint")}</p>
          </header>
          {stage === "language" ? (
            <fieldset className={styles.languages}>
              <legend className="sr-only">{t("languageTitle")}</legend>
              {locales.map((option) => {
                const checked = (chosenLocale ?? locale) === option;
                return (
                  <label key={option} className={styles.language}>
                    <input
                      className={styles.languageInput}
                      type="radio"
                      name={`${titleId}-language`}
                      value={option}
                      checked={checked}
                      onChange={() => {
                        setChosenLocale(option);
                        chooseLocale(option);
                      }}
                    />
                    <span className={styles.flag} aria-hidden>
                      {getLocaleFlag(option)}
                    </span>
                    <span lang={option} className={styles.languageName}>
                      {getLocaleLabel(option)}
                    </span>
                    {checked && <Check className={styles.check} aria-hidden />}
                  </label>
                );
              })}
            </fieldset>
          ) : (
            <StartPreferencesAppearance />
          )}
        </section>
      </div>
      <footer className={styles.footer} data-start-preferences-navigation>
        <Button
          type="button"
          variant="ghost"
          disabled={stage === "language"}
          onClick={() => changeStage("language")}
        >
          <ArrowLeft className="size-4" aria-hidden />
          {guided("back")}
        </Button>
        <span className={styles.position} aria-live="polite">
          {t("position", { current: stage === "language" ? 1 : 2, total: 2 })}
        </span>
        <Button
          type="button"
          onClick={() => {
            if (stage === "language") {
              chooseLocale(chosenLocale ?? locales.find((item) => item === locale) ?? "en", {
                navigate: false,
              });
              changeStage("appearance");
            } else onContinue();
          }}
        >
          {t(stage === "language" ? "continue" : "finish")}
          <ArrowRight className="size-4" aria-hidden />
        </Button>
      </footer>
    </div>
  );
}
