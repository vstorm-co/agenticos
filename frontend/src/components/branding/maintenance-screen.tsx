"use client";

import { Wrench } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import styles from "./deployment-notice.module.css";
import { useBranding } from "@/components/branding/branding-provider";

/**
 * What the product shows while a maintenance window is open.
 *
 * Not the whole of the mechanism, and deliberately the smaller half: the API is
 * already refusing everything outside its allow-list, so without this page a user
 * would get a dashboard of failed queries and error states - the same outage,
 * described worse. This says what is happening and, if the operator wrote one, why.
 *
 * The deployment's own administrator never sees it. They are the one who has to
 * turn the window off, and hiding the console from them is how a maintenance mode
 * becomes an outage.
 */
export function MaintenanceScreen({
  message,
  plannedEnd,
}: {
  message?: string | null;
  plannedEnd?: string | null;
}) {
  const t = useTranslations("pages.maintenance");
  const format = useFormatter();
  const timing = useTranslations("consoleExperience");
  const { appName, maintenanceMessage, maintenancePlannedEndAt } = useBranding();
  // Undefined means the authenticated poll has not answered; null clears an old custom message.
  const currentMessage = message === undefined ? maintenanceMessage : message;
  const currentEnd = plannedEnd === undefined ? maintenancePlannedEndAt : plannedEnd;

  return (
    <div className={styles.maintenance}>
      <section className={styles.maintenanceCard}>
        <span className={styles.maintenanceMark} aria-hidden>
          <Wrench className="size-6" />
        </span>
        <p className={styles.eyebrow}>{t("status")}</p>
        <h1>{t("heading", { app: appName })}</h1>
        <p className={styles.maintenanceMessage}>{currentMessage || t("body")}</p>
        {currentEnd && (
          <p className="text-muted-foreground mt-4 text-sm">
            {timing("maintenanceEnd")}
            {": "}
            <time dateTime={currentEnd}>
              {format.dateTime(new Date(currentEnd), { dateStyle: "medium", timeStyle: "short" })}
            </time>
            <span className="mt-1 block text-xs">{timing("maintenanceEndInformational")}</span>
          </p>
        )}
      </section>
    </div>
  );
}
