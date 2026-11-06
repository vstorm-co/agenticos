"use client";

import { useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  FormField,
  Textarea,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { reviewDecisionCase, type MemoryClaim } from "@/lib/memory-api";

export function DecisionEvidence({ claim }: { claim: MemoryClaim }) {
  const formId = useId();
  const t = useTranslations("pages.memory.claims.episode");
  const errors = useTranslations("errors");
  const [open, setOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const episode = claim.episode;
  const [input, setInput] = useState(episode?.situation ?? "");
  const [reference, setReference] = useState(episode?.correction ?? episode?.choice ?? "");
  const exportCase = useMutation({
    mutationFn: () => reviewDecisionCase(claim.id, input.trim(), reference.trim()),
    onSuccess: (data) => {
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data) + "\n"], { type: "application/x-ndjson" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `decision-${claim.id}.jsonl`;
      link.click();
      URL.revokeObjectURL(url);
      setOpen(false);
    },
  });
  if (!episode) return null;
  const fields = [
    ["situation", episode.situation],
    ["choice", episode.choice],
    ["alternatives", episode.alternatives.join("; ")],
    ["expected", episode.expected_outcome],
    ["actual", episode.actual_outcome],
    ["correction", episode.correction],
  ] as const;
  return (
    <>
      <dl className="grid gap-5 text-sm sm:grid-cols-2">
        {fields.map(([label, value]) =>
          value ? (
            <div
              key={label}
              className={label === "situation" || label === "choice" ? "sm:col-span-2" : undefined}
            >
              <dt className="text-muted-foreground mb-1.5 text-xs font-medium">{t(label)}</dt>
              <dd className="leading-6 whitespace-pre-wrap">{value}</dd>
            </div>
          ) : null,
        )}
      </dl>
      {claim.status === "current" || claim.status === "disputed" ? (
        <Button
          variant="outline"
          size="sm"
          className="mt-6"
          onClick={() => {
            setConfirmed(false);
            setOpen(true);
          }}
        >
          {t("export")}
        </Button>
      ) : null}
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!exportCase.isPending) setOpen(next);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("export")}</DialogTitle>
            <DialogDescription>{t("review")}</DialogDescription>
          </DialogHeader>
          <FormField htmlFor={`${formId}-input`} label={t("input")}>
            <Textarea
              maxLength={32000}
              aria-label={t("input")}
              value={input}
              onChange={(event) => {
                setInput(event.target.value);
                setConfirmed(false);
              }}
            />
          </FormField>
          <FormField htmlFor={`${formId}-reference`} label={t("reference")}>
            <Textarea
              maxLength={32000}
              aria-label={t("reference")}
              value={reference}
              onChange={(event) => {
                setReference(event.target.value);
                setConfirmed(false);
              }}
            />
          </FormField>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={confirmed}
              onCheckedChange={(value) => setConfirmed(value === true)}
            />
            {t("consent")}
          </label>
          {exportCase.error ? (
            <p role="alert">{getErrorMessage(exportCase.error, errors)}</p>
          ) : null}
          <Button
            disabled={!confirmed || !input.trim() || !reference.trim() || exportCase.isPending}
            onClick={() => exportCase.mutate()}
          >
            {t("download")}
          </Button>
        </DialogContent>
      </Dialog>
    </>
  );
}
