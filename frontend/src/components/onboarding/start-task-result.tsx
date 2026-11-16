"use client";

import { useLocale, useTranslations } from "next-intl";
import { Check, CircleHelp } from "lucide-react";
import type { StartGoal } from "@/lib/onboarding-api";
import styles from "./workbench.module.css";

const OFFERS = [
  { name: "A", price: 80, seats: 5, hours: 48 },
  { name: "B", price: 95, seats: 8, hours: 12 },
  { name: "C", price: 120, seats: 15, hours: 4 },
];

/** Curated fictional results, never output from the viewer's agent or edits. */
export function StartTaskResult({ goal }: { goal: StartGoal }) {
  const t = useTranslations("start");
  const locale = useLocale();
  if (goal === "document")
    return (
      <div className={styles.answers}>
        <section>
          <h3>{t("workbench.policyQuestion")}</h3>
          <p>{t("workbench.policyAnswer")}</p>
          <blockquote>{t("workbench.policyQuote")}</blockquote>
        </section>
        <section>
          <h3>{t("workbench.monitorQuestion")}</h3>
          <p>{t("workbench.monitorAnswer")}</p>
        </section>
      </div>
    );
  return (
    <div className={styles.resultDocument}>
      <h3 className="sr-only">
        {t(goal === "meeting" ? "workbench.actionPlan" : "workbench.offerComparison")}
      </h3>
      <div className={styles.tableFrame}>
        {goal === "meeting" ? (
          <table>
            <caption className="sr-only">{t("workbench.actionPlan")}</caption>
            <thead>
              <tr>
                <th>{t("workbench.task")}</th>
                <th>{t("workbench.owner")}</th>
                <th>{t("workbench.due")}</th>
              </tr>
            </thead>
            <tbody>
              {(["proposal", "budget", "update"] as const).map((row) => (
                <tr key={row}>
                  <th scope="row">{t(`workbench.plan.${row}.task`)}</th>
                  <td data-missing={row === "update"}>{t(`workbench.plan.${row}.owner`)}</td>
                  <td data-missing={row === "budget"}>{t(`workbench.plan.${row}.due`)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <table data-kind="compare">
            <caption className="sr-only">{t("workbench.offerComparison")}</caption>
            <thead>
              <tr>
                <th>{t("workbench.offer")}</th>
                <th>{t("workbench.monthlyPrice")}</th>
                <th>{t("workbench.seats")}</th>
                <th>{t("workbench.support")}</th>
              </tr>
            </thead>
            <tbody>
              {OFFERS.map((offer) => (
                <tr key={offer.name} data-recommended={offer.name === "B"}>
                  <th scope="row">
                    <span className={styles.offerName}>
                      {offer.name}
                      {offer.name === "B" && <Check size={14} aria-hidden />}
                    </span>
                  </th>
                  <td className={styles.number}>
                    {new Intl.NumberFormat(locale, {
                      style: "currency",
                      currency: "EUR",
                      maximumFractionDigits: 0,
                    }).format(offer.price)}
                  </td>
                  <td className={styles.number}>{offer.seats}</td>
                  <td className={styles.number}>{t("workbench.hours", { count: offer.hours })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className={styles.resultInsight}>
        {goal === "meeting" ? (
          <CircleHelp size={16} aria-hidden />
        ) : (
          <Check size={16} aria-hidden />
        )}
        {t(goal === "meeting" ? "workbench.planInsight" : "workbench.offerInsight")}
      </p>
    </div>
  );
}
