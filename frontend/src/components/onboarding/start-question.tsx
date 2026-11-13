"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui";
import { StartGuide } from "./start-guide";
import styles from "./guided-start.module.css";

export function StartQuestion({
  index,
  total,
  title,
  message,
  children,
  pending = false,
  onBack,
  onContinue,
  onSkip,
}: {
  index: number;
  total: number;
  title: string;
  message: string;
  children: ReactNode;
  pending?: boolean;
  onBack?: () => void;
  onContinue: () => void;
  onSkip?: () => void;
}) {
  const t = useTranslations("start.guided");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, [index]);
  return (
    <div className={styles.journey}>
      <StartGuide message={message} />
      <section key={index} className={styles.question} aria-label={title}>
        <div className={styles.questionMeta}>
          <span>{t("question", { current: index + 1, total })}</span>
          <span>{t("changeLater")}</span>
        </div>
        <h2 ref={heading} tabIndex={-1}>
          {title}
        </h2>
        <div className={styles.answer}>{children}</div>
        <footer className={styles.actions}>
          {onBack && (
            <Button variant="ghost" disabled={pending} onClick={onBack}>
              <ArrowLeft size={15} aria-hidden />
              {t("back")}
            </Button>
          )}
          {onSkip && (
            <Button variant="ghost" disabled={pending} onClick={onSkip}>
              {t("keepCurrent")}
            </Button>
          )}
          <Button disabled={pending} onClick={onContinue}>
            {pending ? t("saving") : t("continue")}
            <ArrowRight size={15} aria-hidden />
          </Button>
        </footer>
      </section>
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
  const t = useTranslations("start.guided");
  return (
    <div>
      {children}
      {onBack && (
        <div className="flex justify-center">
          <Button variant="ghost" onClick={onBack}>
            <ArrowLeft size={15} aria-hidden />
            {t("back")}
          </Button>
        </div>
      )}
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
