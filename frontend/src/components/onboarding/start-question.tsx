"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui";
import { StartActions, StartBack } from "./start-navigation";
import { StartStageArtwork } from "./start-stage-artwork";
import layout from "./administration.module.css";
import { useStartVariant } from "./start-experience";
import { StartGuide } from "./start-guide";
import styles from "./guided-start.module.css";

export function StartQuestion({
  stage,
  index,
  title,
  message,
  children,
  pending = false,
  onBack,
  onContinue,
  onSkip,
}: {
  stage: "deployment" | "organization";
  index: number;
  title: string;
  message: string;
  children: ReactNode;
  pending?: boolean;
  onBack?: () => void;
  onContinue: () => void;
  onSkip?: () => void;
}) {
  const t = useTranslations("start.guided");
  const studio = useStartVariant() === "studio";
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, [index]);
  return (
    <div className={styles.journey}>
      <h2 ref={heading} tabIndex={-1} className={styles.questionTitle}>
        {title}
      </h2>
      <StartGuide message={message} />
      <div className={studio ? styles.studioLayout : layout.stageStudio}>
        <section
          key={index}
          className={studio ? styles.studioQuestion : styles.question}
          aria-label={title}
        >
          <div className={styles.answer}>{children}</div>
          <StartActions back={onBack && <StartBack onClick={onBack} disabled={pending} />}>
            {onSkip && (
              <Button variant="ghost" disabled={pending} onClick={onSkip}>
                {t("keepCurrent")}
              </Button>
            )}
            <Button disabled={pending} onClick={onContinue}>
              {pending ? t("saving") : t("continue")}
              <ArrowRight size={15} aria-hidden />
            </Button>
          </StartActions>
        </section>
        {!studio && <StartStageArtwork stage={stage} />}
      </div>
    </div>
  );
}

/**
 * A question step that has no question to show yet - loading, or failed to read
 * its settings - with the way out of it. The wizard's own Back is hidden on a
 * step asked as questions, so without this a slow or failed read is a dead end.
 */
export function StartStepPending({
  children,
  onBack,
}: {
  children: ReactNode;
  onBack?: () => void;
}) {
  return (
    <div>
      {children}
      <StartActions back={onBack && <StartBack onClick={onBack} />} />
    </div>
  );
}

/** A question step whose settings could not be read: retry, or leave the step. */
export function StartStepFailed({ onRetry, onBack }: { onRetry: () => void; onBack?: () => void }) {
  const t = useTranslations("start.guided");
  return (
    <StartStepPending onBack={onBack}>
      <ErrorState title={t("loadFailed")} cta={{ label: t("retry"), onClick: onRetry }} />
    </StartStepPending>
  );
}
