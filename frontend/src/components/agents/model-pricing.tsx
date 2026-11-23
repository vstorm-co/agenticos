"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { FormField, Input, Switch } from "@/components/ui";
import type { TokenPricing } from "@/types/providers";

const RATES = ["input", "output", "cache_read", "cache_write"] as const;

export function sameTokenPricing(left: TokenPricing | null, right: TokenPricing | null): boolean {
  if (left === null || right === null) return left === right;
  return RATES.every((field) => (left[field] ?? null) === (right[field] ?? null));
}

export function validTokenPricing(value: TokenPricing | null): boolean {
  if (value === null) return true;
  return RATES.every((field) => {
    const rate = value[field];
    if (rate == null || rate === "") return field === "cache_read" || field === "cache_write";
    return (
      rate.trim() !== "" &&
      Number.isFinite(Number(rate)) &&
      Number(rate) >= 0 &&
      Number(rate) <= 1_000_000
    );
  });
}

export function ModelPricing({
  value,
  automatic,
  disabled,
  onChange,
}: {
  value: TokenPricing | null;
  automatic?: TokenPricing | null;
  disabled?: boolean;
  onChange: (value: TokenPricing | null) => void;
}) {
  const t = useTranslations("modelPricing");
  const id = useId();
  return (
    <fieldset disabled={disabled} className="space-y-3">
      <legend className="text-sm font-medium">{t("title")}</legend>
      <p className="text-muted-foreground text-xs">
        {t(automatic ? "automaticAvailable" : "automaticUnavailable")}
      </p>
      {automatic && (
        <dl className="text-muted-foreground grid grid-cols-2 gap-2 text-xs">
          {RATES.map((field) => (
            <div key={field}>
              <dt>{t(field)}</dt>
              <dd>{automatic[field] ?? automatic.input}</dd>
            </div>
          ))}
        </dl>
      )}
      <label htmlFor={`${id}-override`} className="flex items-center gap-2 text-sm">
        <Switch
          id={`${id}-override`}
          checked={value !== null}
          disabled={disabled}
          onCheckedChange={(checked) =>
            onChange(
              checked
                ? {
                    input: automatic?.input ?? "",
                    output: automatic?.output ?? "",
                    cache_read: null,
                    cache_write: null,
                  }
                : null,
            )
          }
        />
        {t("override")}
      </label>
      {value !== null && (
        <div className="grid grid-cols-2 gap-3">
          {RATES.map((field) => (
            <FormField
              key={field}
              htmlFor={`${id}-${field}`}
              label={t(field)}
              description={
                field === "cache_read" || field === "cache_write" ? t("cacheDefault") : undefined
              }
            >
              <Input
                id={`${id}-${field}`}
                type="number"
                min="0"
                max="1000000"
                step="any"
                required={field === "input" || field === "output"}
                value={value[field] ?? ""}
                onChange={(event) =>
                  onChange({
                    ...value,
                    [field]:
                      event.target.value === "" &&
                      (field === "cache_read" || field === "cache_write")
                        ? null
                        : event.target.value,
                  })
                }
              />
            </FormField>
          ))}
        </div>
      )}
    </fieldset>
  );
}
