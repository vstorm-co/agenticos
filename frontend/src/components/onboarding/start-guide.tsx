"use client";

import { useTranslations } from "next-intl";
import { AvatarFace } from "@/components/ui/avatar-face";
import styles from "./guided-start.module.css";

/** Scripted interface guidance; never a generated answer or an agent run. */
export function StartGuide({ message }: { message: string }) {
  const t = useTranslations("start.guided");
  return (
    <aside className={styles.guide} aria-label={t("guideLabel")}>
      <span className={styles.face} aria-hidden>
        <AvatarFace seed="agenticos" />
      </span>
      <div>
        <span className={styles.guideName}>
          {t("guideName")} <small>{t("guideLabel")}</small>
        </span>
        <p key={message} className={styles.message} aria-live="polite">
          {message}
        </p>
      </div>
    </aside>
  );
}
