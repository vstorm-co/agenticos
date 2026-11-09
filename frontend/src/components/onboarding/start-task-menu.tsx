"use client";

import { LoaderCircle, NotebookPen, FileText, Columns3, Check } from "lucide-react";
import { useTranslations } from "next-intl";
import { Label } from "@/components/ui";
import { START_GOALS, type StartGoal } from "@/lib/onboarding-api";
import { StartCompanions } from "./start-companions";
import styles from "./workbench.module.css";

const ICONS = { meeting: NotebookPen, document: FileText, compare: Columns3 };

export function StartTaskMenu({
  goal,
  savedGoal,
  saving,
  onChange,
}: {
  goal: StartGoal;
  savedGoal: StartGoal | null;
  saving: boolean;
  onChange: (goal: StartGoal) => void;
}) {
  const t = useTranslations("start");
  return (
    <aside className={styles.taskMenu}>
      <h2 id="start-choices" className={styles.menuTitle}>
        {t("workbench.choose")}
      </h2>
      <fieldset aria-labelledby="start-choices" className={styles.choices} disabled={saving}>
        {START_GOALS.map((item) => {
          const Icon = ICONS[item];
          return (
            <Label
              key={item}
              htmlFor={`start-${item}`}
              className={styles.choice}
              data-selected={goal === item}
              data-goal={item}
            >
              <Icon size={18} aria-hidden />
              <span>
                <strong>{t(`workbench.goals.${item}`)}</strong>
                <span>{t(`examples.${item}.description`)}</span>
              </span>
              <input
                type="radio"
                name="start-goal"
                checked={goal === item}
                onChange={() => onChange(item)}
                id={`start-${item}`}
                value={item}
                className={styles.radio}
              />
            </Label>
          );
        })}
      </fieldset>
      <p className={styles.saved} role="status">
        {saving ? (
          <>
            <LoaderCircle
              size={13}
              className="animate-spin motion-reduce:animate-none"
              aria-hidden
            />
            {t("workbench.saving")}
          </>
        ) : savedGoal === goal ? (
          <>
            <Check size={13} aria-hidden />
            {t("workbench.saved")}
          </>
        ) : null}
      </p>
      <StartCompanions />
      <p className={styles.menuHint}>{t("workbench.menuHint")}</p>
    </aside>
  );
}
