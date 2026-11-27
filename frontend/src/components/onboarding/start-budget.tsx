"use client";

import { MonetaryInput } from "@/components/money/monetary-input";
import { useMonetaryInputs } from "@/hooks/use-monetary-inputs";
import { canonicalUsd } from "@/lib/money";
import { useMoney } from "@/components/providers/currency-provider";

import { useId, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useOrganizations } from "@/hooks/use-organizations";
import { getErrorMessage } from "@/lib/api-error";
import { useChanged } from "@/hooks/use-changed";
import { Button, Label } from "@/components/ui";
import type { Organization } from "@/types";
import { StartQuestion } from "./start-question";
import styles from "./guided-start.module.css";

/** No default is saved by visiting. The cap is committed only by Continue. */
export function StartBudget({
  org,
  onContinue,
  onBack,
}: {
  org: Organization;
  onContinue: () => void;
  /** Back out of the step this question opens. */
  onBack?: () => void;
}) {
  const monetary = useMonetaryInputs(org.id);
  const money = useMoney();
  const tm = useTranslations("currencies");
  const t = useTranslations("start.guided");
  const inputId = useId();
  const errorId = `${inputId}-error`;
  const hintId = `${inputId}-hint`;
  const locale = useLocale();
  const errors = useTranslations("errors");
  const { setMonthlyBudget } = useOrganizations();
  const stored = canonicalUsd(org.monthly_budget_usd);
  const [value, setValue] = useState(stored);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (useChanged(`${org.id}|${stored}`)) setValue(stored);
  const parsed = value === "" ? null : value;
  const reporting = parsed === null ? null : money.amount(parsed);
  const valid =
    parsed === null || (money.plan(money.inputValue(parsed)) !== null && parsed !== "0");
  const formatted = parsed === null ? t("unlimited") : money.format(parsed, locale, 0);
  const choose = (next: string) => {
    setValue(next);
    setError(null);
  };
  const chooseReporting = (text: string) => {
    const write = text === "" ? null : money.plan(text);
    monetary.change("monthly_budget_usd", write, text === "" || write !== null);
    if (text === "" || write !== null) choose(write?.usd ?? "");
  };
  const submit = async () => {
    if (!valid) {
      setError(t("budgetInvalid"));
      return;
    }
    if (value === stored && !monetary.has("monthly_budget_usd")) {
      onContinue();
      return;
    }
    setPending(true);
    try {
      await setMonthlyBudget(org.id, parsed, monetary.payload({}).monetary_inputs);
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
      stage="organization"
      index={0}
      title={t("budgetTitle")}
      message={t("budgetGuide")}
      pending={pending}
      onBack={onBack}
      onContinue={() => void submit()}
      onSkip={onContinue}
    >
      <div className={styles.budgetLayout}>
        <div>
          <div className={styles.budgetField}>
            <Label htmlFor={inputId}>
              {tm("budgetLabel", { currency: money.currency ?? "—" })}
            </Label>
            <MonetaryInput
              id={inputId}
              monetary={monetary}
              field="monthly_budget_usd"
              placeholder={t("unlimited")}
              value={value}
              disabled={pending}
              aria-invalid={!valid}
              aria-describedby={error ? `${hintId} ${errorId}` : hintId}
              onValueChange={choose}
              onInvalidValueChange={choose}
            />
          </div>
          <input
            type="range"
            className={styles.budgetSlider}
            min={1}
            max={Math.max(
              1000,
              Math.ceil((valid && reporting !== null ? reporting : 0) / 500) * 500,
            )}
            step={1}
            value={valid && reporting !== null ? Math.round(reporting) : 0}
            disabled={pending || parsed === null || !money.available}
            aria-label={t("budgetSlider", { currency: money.currency ?? "—" })}
            aria-valuetext={formatted}
            onChange={(event) => chooseReporting(String(Math.round(Number(event.target.value))))}
          />
          <div className={styles.presets}>
            {[25, 100, 500].map((amount) => (
              <Button
                key={amount}
                variant={reporting === amount ? "secondary" : "outline"}
                aria-pressed={reporting === amount}
                disabled={pending || !money.available}
                onClick={() => chooseReporting(String(amount))}
              >
                {money.formatAmount(amount, locale, 0)}
              </Button>
            ))}
            <Button
              variant={parsed === null ? "secondary" : "outline"}
              aria-pressed={parsed === null}
              disabled={pending}
              onClick={() => chooseReporting("")}
            >
              {t("unlimited")}
            </Button>
          </div>
        </div>
        <p id={hintId} className={styles.hint}>
          {t("budgetHint")}
        </p>
        {error && (
          <p id={errorId} role="alert" className="text-destructive-ink mt-4 text-sm">
            {error}
          </p>
        )}
      </div>
    </StartQuestion>
  );
}
