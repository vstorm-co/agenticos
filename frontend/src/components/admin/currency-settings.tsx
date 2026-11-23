"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  FormField,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { CurrencySettings } from "@/lib/currency-api";

export function CurrencySettingsEditor({
  value,
  effective,
  disabled,
  onChange,
}: {
  value: CurrencySettings | null;
  effective: CurrencySettings;
  disabled?: boolean;
  onChange: (value: CurrencySettings | null) => void;
}) {
  const t = useTranslations("currencies");
  const id = useId();
  const [code, setCode] = useState("");
  const [rate, setRate] = useState("");
  const current = value ?? effective;
  const entries = Object.entries(current.rates);
  const canAdd =
    /^[A-Z]{3}$/.test(code) &&
    !(code in current.rates) &&
    Number(rate) > 0 &&
    Number.isFinite(Number(rate));
  return (
    <fieldset disabled={disabled} className="space-y-4">
      <legend className="text-sm font-medium">{t("title")}</legend>
      <p className="text-muted-foreground text-sm">{t("manualRates")}</p>
      <FormField label={t("deploymentDefault")} htmlFor={`${id}-default`}>
        <Select
          value={current.default_currency}
          disabled={disabled}
          onValueChange={(currency) => onChange({ ...current, default_currency: currency })}
        >
          <SelectTrigger id={`${id}-default`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {entries.map(([currency]) => (
              <SelectItem key={currency} value={currency}>
                {currency}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      {entries.map(([currency, amount]) => (
        <div className="flex items-end gap-2" key={currency}>
          <FormField label={t("rate", { currency })} htmlFor={`${id}-${currency}`}>
            <Input
              id={`${id}-${currency}`}
              type="number"
              min="0"
              step="any"
              disabled={currency === "USD"}
              value={amount}
              onChange={(event) =>
                onChange({
                  ...current,
                  rates: { ...current.rates, [currency]: event.target.value },
                })
              }
            />
          </FormField>
          <Button
            type="button"
            variant="ghost"
            disabled={disabled || currency === "USD" || currency === current.default_currency}
            onClick={() =>
              onChange({
                ...current,
                rates: Object.fromEntries(entries.filter(([key]) => key !== currency)),
              })
            }
          >
            {t("remove", { currency })}
          </Button>
        </div>
      ))}
      <div className="flex flex-wrap items-end gap-2">
        <FormField label={t("code")} htmlFor={`${id}-code`}>
          <Input
            id={`${id}-code`}
            maxLength={3}
            value={code}
            onChange={(event) => setCode(event.target.value.toUpperCase())}
          />
        </FormField>
        <FormField label={t("newRate")} htmlFor={`${id}-rate`}>
          <Input
            id={`${id}-rate`}
            type="number"
            min="0"
            step="any"
            value={rate}
            onChange={(event) => setRate(event.target.value)}
          />
        </FormField>
        <Button
          type="button"
          variant="outline"
          disabled={disabled || !canAdd}
          onClick={() => {
            onChange({ ...current, rates: { ...current.rates, [code]: rate } });
            setCode("");
            setRate("");
          }}
        >
          {t("add")}
        </Button>
      </div>
      {value !== null && (
        <Button type="button" variant="ghost" onClick={() => onChange(null)}>
          {t("reset")}
        </Button>
      )}
    </fieldset>
  );
}
