"use client";

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
import { describeCheck } from "@/lib/scoring";
import {
  CHECK_KINDS,
  CHECK_TYPES,
  isKnownCheck,
  type CheckDraft,
  type CheckType,
} from "./case-form";

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
  label,
  disabled,
  onChange,
}: {
  check: CheckDraft;
  label: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const t = useTranslations("datasets");
  if (!isKnownCheck(check.type)) {
    return (
      <p className="text-muted-foreground flex-1 py-2 font-mono text-xs break-all">
        {describeCheck({ type: check.type, ...check.rest })}
      </p>
    );
  }
  const { as } = CHECK_KINDS[check.type];
  const placeholder = TYPED[check.type] ?? t(`checkPlaceholder.${check.type}`);
  if (as === "json" || check.type === "judge") {
    return (
      <Textarea
        disabled={disabled}
        rows={2}
        value={check.value}
        aria-label={label}
        className={as === "json" ? "font-mono text-xs" : undefined}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
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
      onChange={(event) => onChange(event.target.value)}
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
        <div key={index} className="flex items-start gap-2">
          <Select
            value={check.type}
            disabled={disabled || !isKnownCheck(check.type)}
            onValueChange={(type) => change(index, { type, value: "", rest: {} })}
          >
            <SelectTrigger
              className="w-44 shrink-0"
              aria-label={t("checkTypeOf", { number: index + 1 })}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CHECK_TYPES.map((type) => (
                <SelectItem key={type} value={type}>
                  {t(`checkTypes.${type}`)}
                </SelectItem>
              ))}
              {!isKnownCheck(check.type) && (
                <SelectItem value={check.type}>{check.type}</SelectItem>
              )}
            </SelectContent>
          </Select>
          <CheckValue
            check={check}
            disabled={disabled}
            label={t("checkValue", { number: index + 1 })}
            onChange={(value) => change(index, { value })}
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
