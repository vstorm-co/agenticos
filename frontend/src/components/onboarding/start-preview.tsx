"use client";

import { useRef } from "react";
import { useTranslations } from "next-intl";
import { ArrowLeft, FileText } from "lucide-react";
import {
  Button,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui";
import type { StartGoal } from "@/lib/onboarding-api";
import styles from "./start.module.css";

/** Recorded material stays separate from an editable task and never starts a run. */
export function StartPreview({
  goal,
  onClose,
  onRestoreFocus,
}: {
  goal: StartGoal;
  onClose: () => void;
  onRestoreFocus: () => void;
}) {
  const t = useTranslations("start");
  const heading = useRef<HTMLHeadingElement>(null);
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent
        className={styles.preview}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          heading.current?.focus();
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          onRestoreFocus();
        }}
      >
        <header className={styles.previewHeader}>
          <p className={styles.previewLabel}>
            <FileText size={15} aria-hidden />
            {t("preview")}
          </p>
          <DialogTitle ref={heading} tabIndex={-1} className="focus:outline-none">
            {t(`examples.${goal}.title`)}
          </DialogTitle>
          <DialogDescription>{t("demoHint")}</DialogDescription>
        </header>
        <div className={styles.previewBody}>
          <section className={styles.previewMaterial}>
            <h3>{t("material")}</h3>
            <p>{t(`examples.${goal}.prompt`)}</p>
          </section>
          <section className={styles.previewResult}>
            <h3>{t("recordedExample")}</h3>
            <p>{t(`examples.${goal}.result`)}</p>
          </section>
        </div>
        <footer className={styles.previewFooter}>
          <p className={styles.note} role="note">
            {t("demoNotRun")}
          </p>
          <DialogClose asChild>
            <Button variant="outline">
              <ArrowLeft size={15} aria-hidden />
              {t("back")}
            </Button>
          </DialogClose>
        </footer>
      </DialogContent>
    </Dialog>
  );
}
