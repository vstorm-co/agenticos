"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useOrganizations } from "@/hooks/use-organizations";
import { getErrorMessage } from "@/lib/api-error";
import { useChanged } from "@/hooks/use-changed";
import { Button } from "@/components/ui";
import type { Organization } from "@/types";
import { StartQuestion } from "./start-question";
import styles from "./guided-start.module.css";

/** No default is saved by visiting. The cap is committed only by Continue. */
export function StartBudget({ org, onContinue }: { org: Organization; onContinue: () => void }) {
  const t = useTranslations("start.guided");
  const locale = useLocale();
  const errors = useTranslations("errors");
  const { setMonthlyBudget } = useOrganizations();
  const stored = org.monthly_budget_usd === null ? "" : String(Number(org.monthly_budget_usd));
  const [value, setValue] = useState(stored);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (useChanged(`${org.id}|${stored}`)) setValue(stored);
  const parsed = value === "" ? null : Number(value);
  const valid = parsed === null || (Number.isFinite(parsed) && parsed > 0);
  const formatted =
    parsed === null
      ? t("unlimited")
      : new Intl.NumberFormat(locale, {
          style: "currency",
          currency: "USD",
          maximumFractionDigits: 0,
        }).format(valid ? parsed : 0);
  const choose = (next: string) => {
    setValue(next);
    setError(null);
  };
  const submit = async () => {
    if (!valid) {
      setError(t("budgetInvalid"));
      return;
    }
    if (value === stored) {
      onContinue();
      return;
    }
    setPending(true);
    try {
      await setMonthlyBudget(org.id, parsed);
    } catch (failure) {
      setError(`${t("saveFailed")} ${getErrorMessage(failure, errors)}`);
      return;
    } finally {
      setPending(false);
    }
    onContinue();
  };
  return (
    <StartQuestion
      index={0}
      total={2}
      title={t("budgetTitle")}
      message={t("budgetGuide")}
      pending={pending}
      onContinue={() => void submit()}
      onSkip={onContinue}
    >
      <div className={styles.budgetLayout}>
        <div>
          <div className={styles.amount} aria-live="polite">
            <strong>{formatted}</strong>
            <span>{t(parsed === null ? "unlimitedHint" : "perMonth")}</span>
          </div>
          <input
            type="range"
            className={styles.budgetSlider}
            min={1}
            max={Math.max(1000, Math.ceil((valid && parsed !== null ? parsed : 0) / 500) * 500)}
            step={1}
            value={valid && parsed !== null ? Math.round(parsed) : 0}
            disabled={pending || parsed === null}
            aria-label={t("budgetSlider")}
            aria-valuetext={formatted}
            onChange={(event) => choose(String(Math.round(Number(event.target.value))))}
          />
          <div className={styles.presets}>
            {[25, 100, 500].map((amount) => (
              <Button
                key={amount}
                variant={parsed === amount ? "secondary" : "outline"}
                aria-pressed={parsed === amount}
                disabled={pending}
                onClick={() => choose(String(amount))}
              >
                {new Intl.NumberFormat(locale, {
                  style: "currency",
                  currency: "USD",
                  maximumFractionDigits: 0,
                }).format(amount)}
              </Button>
            ))}
            <Button
              variant={parsed === null ? "secondary" : "outline"}
              aria-pressed={parsed === null}
              disabled={pending}
              onClick={() => choose("")}
            >
              {t("unlimited")}
            </Button>
          </div>
        </div>
        <p className={`${styles.hint} mt-6 text-center`}>{t("budgetHint")}</p>
        {error && (
          <p role="alert" className="text-destructive-ink mt-4 text-sm">
            {error}
          </p>
        )}
      </div>
    </StartQuestion>
  );
}
