"use client";

import { useTranslations } from "next-intl";
import { AvatarFace } from "@/components/ui/avatar-face";
import { useStartVariant } from "./start-experience";
import { StartTypedMessage } from "./start-typed-message";
import experience from "./start-experience.module.css";
import styles from "./guided-start.module.css";

/** Scripted interface guidance; never a generated answer or an agent run. */
export function StartGuide({ message }: { message: string }) {
  const variant = useStartVariant();
  const t = useTranslations("start.guided");
  if (variant === "studio")
    return (
      <p data-start-guide className={experience.helper} aria-live="polite">
        <StartTypedMessage key={message} message={message} />
      </p>
    );
  return (
    <aside data-start-guide className={styles.guide} aria-label={t("guideLabel")}>
      <span className={styles.face} aria-hidden>
        <AvatarFace seed="agenticos" />
      </span>
      <div>
        <span className={styles.guideName}>
          {t("guideName")} <small>{t("guideLabel")}</small>
        </span>
        <p key={message} className={styles.message} aria-live="polite">
          {variant ? <StartTypedMessage key={message} message={message} /> : message}
        </p>
      </div>
    </aside>
  );
}
