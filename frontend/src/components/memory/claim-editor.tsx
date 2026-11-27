"use client";
import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, FormField, Input, Textarea } from "@/components/ui";
import type { MemoryClaim, DecisionEpisode, MemoryValue } from "@/lib/memory-api";

export function ClaimEditor({
  claim,
  historical = false,
  onCancel,
  onSave,
}: {
  claim: MemoryClaim;
  historical?: boolean;
  onCancel: () => void;
  onSave: (
    statement: string,
    effectiveFrom: string | null,
    episode?: DecisionEpisode,
    value?: MemoryValue,
  ) => Promise<void>;
}) {
  const t = useTranslations("pages.memory.claims");
  const id = useId();
  const [statement, setStatement] = useState(claim.statement);
  const [pending, setPending] = useState(false);
  const [from, setFrom] = useState("");
  const [outcome, setOutcome] = useState(claim.episode?.actual_outcome ?? "");
  const [value, setValue] = useState(String(claim.value ?? ""));
  const valueChanged = claim.value != null && value !== String(claim.value);
  const scalar =
    typeof claim.value === "number"
      ? Number(value)
      : typeof claim.value === "boolean"
        ? value === "true"
        : value;
  const invalidNumber =
    valueChanged &&
    typeof scalar === "number" &&
    (value.trim() === "" || !Number.isSafeInteger(scalar));
  const changed =
    statement.trim() !== "" &&
    !invalidNumber &&
    (valueChanged ||
      statement.trim() !== claim.statement ||
      from !== "" ||
      outcome !== (claim.episode?.actual_outcome ?? ""));
  return (
    <fieldset disabled={pending} className="space-y-4">
      <FormField label={t("statement")} htmlFor={`${id}-statement`}>
        <Textarea
          id={`${id}-statement`}
          value={statement}
          maxLength={600}
          onChange={(event) => setStatement(event.target.value)}
          aria-label={t("statement")}
        />
      </FormField>
      {typeof claim.value === "boolean" ? (
        <label className="flex items-center gap-2 text-sm" htmlFor={`${id}-value`}>
          <input
            id={`${id}-value`}
            type="checkbox"
            checked={value === "true"}
            onChange={(event) => setValue(String(event.target.checked))}
          />
          {t("typedValue")}
        </label>
      ) : (
        claim.value != null && (
          <FormField label={t("typedValue")} htmlFor={`${id}-value`}>
            <Input
              id={`${id}-value`}
              type={typeof claim.value === "number" ? "number" : "text"}
              step={typeof claim.value === "number" ? 1 : undefined}
              aria-invalid={invalidNumber}
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
          </FormField>
        )
      )}
      {claim.episode ? (
        <FormField label={t("episode.actual")} htmlFor={`${id}-outcome`}>
          <Textarea
            id={`${id}-outcome`}
            aria-label={t("episode.actual")}
            maxLength={1200}
            value={outcome}
            onChange={(event) => setOutcome(event.target.value)}
          />
        </FormField>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {!historical && (
          <FormField label={t("effectiveFrom")} htmlFor={`${id}-from`}>
            <Input
              id={`${id}-from`}
              type="date"
              value={from}
              onChange={(event) => setFrom(event.target.value)}
            />
          </FormField>
        )}
        <div className="ml-auto flex gap-2">
          <Button variant="outline" size="sm" onClick={onCancel} disabled={pending}>
            {t("cancel")}
          </Button>
          <Button
            size="sm"
            disabled={!changed || pending}
            onClick={async () => {
              setPending(true);
              try {
                await onSave(
                  statement.trim(),
                  from ? `${from}T00:00:00Z` : null,
                  claim.episode
                    ? {
                        ...claim.episode,
                        actual_outcome: outcome.trim() || null,
                        correction: statement.trim(),
                      }
                    : undefined,
                  valueChanged ? scalar : undefined,
                );
              } finally {
                setPending(false);
              }
            }}
          >
            {t("save")}
          </Button>
        </div>
      </div>
    </fieldset>
  );
}
