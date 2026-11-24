"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useCanAddToDataset } from "@/components/datasets/use-dataset-target";
import type { MemoryClaim } from "@/lib/memory-api";
import { ImproveCaseDialog } from "./improve-case-dialog";

export function DecisionEvidence({ claim }: { claim: MemoryClaim }) {
  const t = useTranslations("pages.memory.claims.episode");
  const canAdd = useCanAddToDataset();
  const [open, setOpen] = useState(false);
  const episode = claim.episode;
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
      {(claim.status === "current" || claim.status === "disputed") && canAdd ? (
        <Button variant="outline" size="sm" className="mt-6" onClick={() => setOpen(true)}>
          {t("export")}
        </Button>
      ) : null}
      {open ? (
        <ImproveCaseDialog claim={claim} episode={episode} onClose={() => setOpen(false)} />
      ) : null}
    </>
  );
}
