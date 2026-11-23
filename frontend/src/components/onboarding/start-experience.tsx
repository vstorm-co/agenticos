"use client";

import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowRight, Circle, MessageCircle, PanelsTopLeft, Route } from "lucide-react";
import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";
import { LayoutGroup, motion } from "motion/react";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { AvatarFace } from "@/components/ui/avatar-face";
import { CONTROL_FOCUS } from "@/components/ui/control-styles";
import { START_VARIANTS, startVariant, type StartVariant } from "@/lib/onboarding/variants";
import styles from "./start-experience.module.css";

const StartExperienceContext = createContext<StartVariant | null>(null);

export function useStartVariant() {
  const inherited = useContext(StartExperienceContext);
  const explicit = startVariant(useSearchParams().get("variant"));
  return inherited ?? explicit;
}

/** Animate the mounted scene only after an explicit step change; drafts stay mounted. */
export function useStartTransition(
  ref: RefObject<HTMLElement | null>,
  enabled: boolean,
): (direction: "forward" | "back") => void {
  const reduced = useReducedMotion();
  const animation = useRef<Animation | null>(null);
  useEffect(() => {
    if (reduced || !enabled) animation.current?.cancel();
    return () => animation.current?.cancel();
  }, [reduced, enabled]);
  return (direction: "forward" | "back") => {
    animation.current?.cancel();
    const scene = ref.current;
    if (!enabled || reduced || !scene || typeof scene.animate !== "function") return;
    const tokens = getComputedStyle(document.documentElement);
    const duration = Number.parseFloat(tokens.getPropertyValue("--duration-base"));
    const easing = tokens.getPropertyValue("--ease-out").trim();
    if (!Number.isFinite(duration) || !easing) return;
    animation.current = scene.animate(
      [
        { opacity: 0, transform: `translateX(${direction === "back" ? -24 : 24}px)` },
        { opacity: 1, transform: "translateX(0)" },
      ],
      { duration, easing },
    );
  };
}

export function StartExperience({ children }: { children: ReactNode }) {
  const variant = startVariant(useSearchParams().get("variant")) ?? "studio";
  return (
    <StartExperienceContext.Provider value={variant}>
      <div className={styles.experience} data-onboarding-variant={variant}>
        {children}
      </div>
    </StartExperienceContext.Provider>
  );
}

export function StartVariantPicker() {
  const variant = useStartVariant();
  const t = useTranslations("start.experience");
  if (!variant || variant === "studio") return null;
  const icons = { conversation: MessageCircle, studio: PanelsTopLeft, launchpad: Route };
  return (
    <div className={styles.variantPicker} role="group" aria-label={t("designs")}>
      {START_VARIANTS.map((item) => {
        const Icon = icons[item];
        return (
          <button
            key={item}
            type="button"
            className={CONTROL_FOCUS}
            aria-pressed={item === variant}
            onClick={() => {
              const url = new URL(window.location.href);
              url.searchParams.set("variant", item);
              window.history.replaceState(null, "", url);
            }}
          >
            <Icon size={14} aria-hidden />
            <span>{t(`variants.${item}`)}</span>
          </button>
        );
      })}
    </div>
  );
}

export function StartJourney<T extends string>({
  steps,
  current,
  visited,
  onSelect,
  label,
}: {
  steps: readonly T[];
  current: T;
  visited: readonly T[];
  onSelect: (step: T) => void;
  label: (step: T) => string;
}) {
  const variant = useStartVariant();
  const t = useTranslations("start.experience");
  const journeyId = useId();
  const reduced = useReducedMotion();
  if (!variant) return null;
  const phaseFor = (step: string): string => {
    if (["workspace", "identity", "welcome"].includes(step)) return "workspace";
    if (["profile", "context"].includes(step)) return "you";
    if (["subscriptions", "models"].includes(step)) return "models";
    if (["team", "deployment", "organization"].includes(step)) return "team";
    if (step === "tools") return "tools";
    if (step === "task") return "launch";
    return step;
  };
  const phases = [...new Set(steps.map(phaseFor))];
  const phaseName = (phase: string): string =>
    ["workspace", "you", "models", "tools", "team", "launch"].includes(phase)
      ? t(`phases.${phase}`)
      : label(steps.find((step) => phaseFor(step) === phase)!);
  return (
    <aside className={styles.journey} data-start-journey>
      {variant !== "studio" && (
        <div className={styles.journeyIntro}>
          <span className={styles.journeyFace}>
            <AvatarFace seed="agenticos" />
          </span>
          <div>
            <strong>{t("journeyTitle")}</strong>
            <p>{t(`introductions.${variant}`)}</p>
          </div>
        </div>
      )}
      <LayoutGroup id={journeyId}>
        <nav aria-label={t("journeyTitle")}>
          <ol>
            {phases.map((phase, index) => {
              const phaseSteps = steps.filter((step) => phaseFor(step) === phase);
              const active = phaseFor(current) === phase;
              const target = active ? current : phaseSteps.find((step) => visited.includes(step));
              const name = phaseName(phase);
              return (
                <li key={phase}>
                  <button
                    type="button"
                    className={CONTROL_FOCUS}
                    aria-current={active ? "step" : undefined}
                    disabled={target === undefined}
                    onClick={() => {
                      if (target !== undefined) onSelect(target);
                    }}
                  >
                    <span className={styles.stepNumber}>{String(index + 1).padStart(2, "0")}</span>
                    <span>{name}</span>
                    {variant !== "studio" &&
                      (active ? (
                        <ArrowRight size={14} aria-hidden />
                      ) : (
                        <Circle size={8} aria-hidden />
                      ))}
                    {variant === "studio" && active && (
                      <motion.span
                        aria-hidden
                        className={styles.phaseMarker}
                        layoutId={reduced ? undefined : "phase"}
                        initial={false}
                        transition={
                          reduced
                            ? { duration: 0 }
                            : { type: "spring", stiffness: 360, damping: 34 }
                        }
                      />
                    )}
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>
      </LayoutGroup>
      {variant === "studio" && (
        <div className={styles.mobileProgress}>
          <span aria-current="step">{phaseName(phaseFor(current))}</span>
          <div aria-hidden>
            {phases.map((phase) => (
              <span key={phase} data-current={phase === phaseFor(current)} />
            ))}
          </div>
        </div>
      )}
      {variant !== "studio" && (
        <div className={styles.journeyTeam}>
          <span>
            <AvatarFace seed="architect" />
          </span>
          <p>
            <strong>{t("architectName")}</strong>
            {t("architectAside")}
          </p>
        </div>
      )}
    </aside>
  );
}
