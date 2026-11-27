"use client";

import { useEffect, useId, useRef, useState, type ComponentProps } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Input } from "@/components/ui/input";
import { useMoney } from "@/components/providers/currency-provider";
import { compareUsd, type CurrencyAmount } from "@/lib/money";
import type { MonetaryInputs } from "@/hooks/use-monetary-inputs";

type Props = Omit<
  ComponentProps<typeof Input>,
  "value" | "onChange" | "type" | "min" | "max" | "step"
> & {
  value: string | number | null | undefined;
  field: string;
  monetary: MonetaryInputs;
  maxUsd?: string | number;
  positive?: boolean;
  onValueChange(value: string, input?: CurrencyAmount): void;
  onInvalidValueChange?(value: string): void;
};

/** The visible unit changes; canonical USD and request declarations stay explicit.
 * Invalid text remains editable, has native validity, and cannot become a write.
 */
export function MonetaryInput({
  value,
  field,
  monetary,
  maxUsd,
  positive = false,
  onValueChange,
  onInvalidValueChange,
  disabled,
  ...props
}: Props) {
  const money = useMoney();
  const locale = useLocale();
  const t = useTranslations("currencies");
  const common = useTranslations("common");
  const errorId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const canonical = value == null || value === "" ? "" : String(value);
  const context = `${money.currency}|${money.quote}|${locale}|${monetary.revision}`;
  const shown = money.inputValue(value, locale) || (money.available ? canonical : "");
  const [draft, setDraft] = useState({ text: shown, canonical, context });
  const [error, setError] = useState("");
  useEffect(() => {
    inputRef.current?.setCustomValidity("");
  }, [context]);
  if (draft.canonical !== canonical || draft.context !== context) {
    setDraft({ text: shown, canonical, context });
    setError("");
  }
  const problem = (text: string): string => {
    if (text.trim() === "") return "";
    const write = money.plan(text, locale);
    if (!write) return t("amountInvalid");
    if (positive && compareUsd(write.usd, "0") === 0) return t("amountPositive");
    if (maxUsd !== undefined && compareUsd(write.usd, maxUsd) === 1) {
      return t("amountMaximum", {
        amount: money.inputValue(maxUsd, locale),
        currency: money.currency ?? "—",
      });
    }
    return "";
  };
  return (
    <>
      <Input
        {...props}
        ref={inputRef}
        type="text"
        inputMode="decimal"
        placeholder={
          money.available
            ? props.placeholder
            : money.currency === null
              ? common("loading")
              : t("rateUnavailable", { currency: money.currency })
        }
        disabled={disabled || !money.available}
        value={draft.text}
        aria-invalid={Boolean(props["aria-invalid"] || error)}
        aria-describedby={
          [props["aria-describedby"], error ? errorId : null].filter(Boolean).join(" ") || undefined
        }
        onChange={(event) => {
          const text = event.target.value;
          const empty = text.trim() === "";
          const failure = problem(text);
          const write = empty || failure ? null : money.plan(text, locale);
          const next = empty ? "" : (write?.usd ?? (onInvalidValueChange ? text : canonical));
          setDraft({ text, canonical: next, context });
          setError("");
          monetary.change(field, write, failure === "");
          if (empty || write !== null) onValueChange(next, write?.input);
          else onInvalidValueChange?.(text);
          event.target.setCustomValidity(failure);
        }}
        onBlur={(event) => {
          const failure = problem(event.target.value);
          setError(failure);
          event.target.setCustomValidity(failure);
          props.onBlur?.(event);
        }}
      />
      {error && (
        <p id={errorId} role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
    </>
  );
}
