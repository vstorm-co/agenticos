"use client";
import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, FormField, Input, Textarea } from "@/components/ui";
import type { MemoryClaim, DecisionEpisode } from "@/lib/memory-api";

export function ClaimEditor({
  claim,
  onCancel,
  onSave,
}: {
  claim: MemoryClaim;
  onCancel: () => void;
  onSave: (
    statement: string,
    effectiveFrom: string | null,
    episode?: DecisionEpisode,
  ) => Promise<void>;
}) {
  const t = useTranslations("pages.memory.claims");
  const id = useId();
  const [statement, setStatement] = useState(claim.statement);
  const [pending, setPending] = useState(false);
  const [from, setFrom] = useState("");
  const [outcome, setOutcome] = useState(claim.episode?.actual_outcome ?? "");
  const changed =
    statement.trim() !== "" &&
    (statement.trim() !== claim.statement ||
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
        <FormField label={t("effectiveFrom")} htmlFor={`${id}-from`}>
          <Input
            id={`${id}-from`}
            type="date"
            value={from}
            onChange={(event) => setFrom(event.target.value)}
          />
        </FormField>
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
                  ...(claim.episode
                    ? [
                        {
                          ...claim.episode,
                          actual_outcome: outcome.trim() || null,
                          correction: statement.trim(),
                        },
                      ]
                    : []),
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
