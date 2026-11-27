"use client";
import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  OnboardingReminderCard,
  useOnboardingReminder,
} from "@/components/onboarding/onboarding-reminder";
import { DesktopInstallCard, useDesktopInstallPrompt } from "./desktop-install-prompt";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import styles from "./sidebar-promotions.module.css";
function subscribeVisibility(notify: () => void) {
  document.addEventListener("visibilitychange", notify);
  return () => document.removeEventListener("visibilitychange", notify);
}
function documentVisible() {
  return document.visibilityState === "visible";
}
function serverVisible() {
  return false;
}
export function SidebarPromotions({
  collapsed = false,
  onNavigate,
}: {
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const onboarding = useOnboardingReminder();
  const desktop = useDesktopInstallPrompt();
  const setup = (
    <OnboardingReminderCard reminder={onboarding} collapsed={collapsed} onNavigate={onNavigate} />
  );
  if (collapsed) return onboarding.eligible ? setup : null;
  if (onboarding.eligible && desktop.eligible)
    return (
      <PromotionCarousel
        setup={<OnboardingReminderCard reminder={onboarding} onNavigate={onNavigate} embedded />}
        desktop={<DesktopInstallCard dismiss={desktop.dismiss} embedded />}
      />
    );
  if (onboarding.eligible) return setup;
  return desktop.eligible ? <DesktopInstallCard dismiss={desktop.dismiss} /> : null;
}
function PromotionCarousel({ setup, desktop }: { setup: ReactNode; desktop: ReactNode }) {
  const t = useTranslations("layout.sidebarPromotions");
  const reduce = useReducedMotion();
  const documentIsVisible = useSyncExternalStore(
    subscribeVisibility,
    documentVisible,
    serverVisible,
  );
  const [element, setElement] = useState<HTMLElement | null>(null);
  const [inView, setInView] = useState(false);
  const [slide, setSlide] = useState(0);
  const [paused, setPaused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (!element) return;
    const observer = new IntersectionObserver((entries) =>
      setInView(entries.some((entry) => entry.isIntersecting)),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  const rotating = !reduce && !paused && !hovered && !focused && documentIsVisible && inView;
  useEffect(() => {
    if (!rotating) return;
    const timer = window.setInterval(() => setSlide((value) => 1 - value), 8000);
    return () => window.clearInterval(timer);
  }, [rotating]);
  const change = () => {
    setPaused(true);
    setSlide((value) => 1 - value);
  };
  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- This region only pauses automatic changes on hover/focus; its named buttons own all activation.
    <section
      ref={setElement}
      aria-label={t("title")}
      aria-roledescription={t("carousel")}
      className={styles.card}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocusCapture={() => {
        setFocused(true);
        setPaused(true);
      }}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
      }}
    >
      <div className={styles.slides} aria-live={rotating ? "off" : "polite"} aria-atomic="true">
        {[setup, desktop].map((content, index) => (
          <div
            key={index}
            className={styles.slide}
            aria-hidden={slide !== index}
            inert={slide !== index}
            role="group"
            aria-roledescription={t("slide")}
            aria-label={t("position", { current: index + 1, total: 2 })}
          >
            {content}
          </div>
        ))}
      </div>
      <div className={styles.controls}>
        <button type="button" aria-label={t("previous")} onClick={change}>
          <ChevronLeft className="size-3.5" aria-hidden />
        </button>
        <span aria-hidden>{t("position", { current: slide + 1, total: 2 })}</span>
        <button type="button" aria-label={t("next")} onClick={change}>
          <ChevronRight className="size-3.5" aria-hidden />
        </button>
        {!reduce && (
          <button
            type="button"
            aria-label={paused ? t("resume") : t("pause")}
            onClick={() => setPaused((value) => !value)}
          >
            {paused ? (
              <Play className="size-3.5" aria-hidden />
            ) : (
              <Pause className="size-3.5" aria-hidden />
            )}
          </button>
        )}
      </div>
    </section>
  );
}
