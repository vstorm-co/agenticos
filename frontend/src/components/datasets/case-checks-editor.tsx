"use client";

import { MonetaryInput } from "@/components/money/monetary-input";
import { useMonetaryInputs } from "@/hooks/use-monetary-inputs";
import { useMoney } from "@/components/providers/currency-provider";

import { Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { CheckTypeChip } from "./check-type-chip";
import { describeCheck } from "@/lib/scoring";
import {
  CHECK_KINDS,
  CHECK_TYPES,
  isKnownCheck,
  type CheckDraft,
  type CheckType,
} from "./case-form";
import { KeysValue } from "./keys-value";
import { LengthValue } from "./length-value";

/** Placeholders that are what is typed - a pattern, a schema, a number - rather than copy. */
const TYPED: Partial<Record<CheckType, string>> = {
  regex: "\\d+ days",
  json_schema: '{"type": "object"}',
  max_cost_usd: "0.05",
  max_latency_ms: "5000",
};

interface CaseChecksEditorProps {
  checks: CheckDraft[];
  disabled?: boolean;
  onChange: (checks: CheckDraft[]) => void;
}

/** The main parameter of one check, written the way its type takes it. */
function CheckValue({
  check,
  number,
  disabled,
  onChange,
}: {
  check: CheckDraft;
  number: number;
  disabled: boolean;
  onChange: (patch: Partial<CheckDraft>) => void;
}) {
  const t = useTranslations("datasets");
  if (!isKnownCheck(check.type)) {
    return (
      <p className="text-muted-foreground flex-1 py-2 font-mono text-xs break-all">
        {describeCheck({ type: check.type, ...check.rest })}
      </p>
    );
  }
  if (check.type === "max_cost_usd") {
    return <CostCriterion check={check} number={number} disabled={disabled} onChange={onChange} />;
  }
  const { as } = CHECK_KINDS[check.type];
  if (as === "length") {
    return <LengthValue check={check} number={number} disabled={disabled} onChange={onChange} />;
  }
  if (as === "keys") {
    return <KeysValue check={check} number={number} disabled={disabled} onChange={onChange} />;
  }
  const label = t("checkValue", { number });
  const placeholder = TYPED[check.type] ?? t(`checkPlaceholder.${check.type}`);
  if (as === "json" || check.type === "judge") {
    return (
      <Textarea
        disabled={disabled}
        rows={2}
        value={check.value}
        aria-label={label}
        className={as === "json" ? "font-mono text-base md:text-xs" : undefined}
        placeholder={placeholder}
        onChange={(event) => onChange({ value: event.target.value })}
      />
    );
  }
  return (
    <Input
      disabled={disabled}
      value={check.value}
      inputMode={as === "number" ? "decimal" : undefined}
      aria-label={label}
      placeholder={placeholder}
      onChange={(event) => onChange({ value: event.target.value })}
    />
  );
}

function CostCriterion({
  check,
  number,
  disabled,
  onChange,
}: {
  check: CheckDraft;
  number: number;
  disabled: boolean;
  onChange: (patch: Partial<CheckDraft>) => void;
}) {
  const money = useMoney();
  const monetary = useMonetaryInputs();
  const t = useTranslations("datasets");
  return (
    <MonetaryInput
      field="value"
      monetary={monetary}
      value={check.value}
      disabled={disabled}
      aria-label={`${t("checkValue", { number })} (${money.currency ?? "—"})`}
      placeholder={TYPED.max_cost_usd}
      onInvalidValueChange={(value) => onChange({ value, currencyInvalid: true })}
      onValueChange={(value, input) =>
        onChange({ value, currencyInvalid: false, rest: { ...check.rest, monetary_input: input } })
      }
    />
  );
}

/**
 * The rules the answer is checked against: a type picked from the list, and what
 * it checks. A check of a type this build does not know is shown as stored and
 * kept, and can only be removed.
 */
export function CaseChecksEditor({ checks, onChange, disabled = false }: CaseChecksEditorProps) {
  const t = useTranslations("datasets");
  const change = (index: number, patch: Partial<CheckDraft>) =>
    onChange(checks.map((check, at) => (at === index ? { ...check, ...patch } : check)));

  return (
    <div className="space-y-2">
      {checks.map((check, index) => (
        <div
          key={index}
          className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2 rounded-lg border p-3"
        >
          <Select
            value={check.type}
            disabled={disabled || !isKnownCheck(check.type)}
            onValueChange={(type) => change(index, { type, value: "", rest: {} })}
          >
            <SelectTrigger
              className="col-span-2 w-full min-w-0"
              aria-label={t("checkTypeOf", { number: index + 1 })}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CHECK_TYPES.map((type) => (
                <SelectItem key={type} value={type} textValue={t(`checkTypes.${type}`)}>
                  <CheckTypeChip type={type} />
                </SelectItem>
              ))}
              {!isKnownCheck(check.type) && (
                <SelectItem value={check.type}>
                  <CheckTypeChip type={check.type} />
                </SelectItem>
              )}
            </SelectContent>
          </Select>
          <CheckValue
            check={check}
            disabled={disabled}
            number={index + 1}
            onChange={(patch) => change(index, patch)}
          />
          <Button
            disabled={disabled}
            variant="ghost"
            size="icon"
            aria-label={t("removeCheck", { number: index + 1 })}
            onClick={() => onChange(checks.filter((_, at) => at !== index))}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      ))}
      <Button
        disabled={disabled}
        variant="outline"
        size="sm"
        onClick={() => onChange([...checks, { type: "contains", value: "", rest: {} }])}
      >
        <Plus className="h-4 w-4" />
        {t("addCheck")}
      </Button>
    </div>
  );
}
