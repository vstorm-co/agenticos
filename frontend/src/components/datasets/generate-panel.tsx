"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { CASE_ORIGINS } from "@/types/case-generation";
import { GenerateCasesDialog } from "./generate-cases-dialog";
import { ProposedCases } from "./proposed-cases";

export function GeneratePanel({ datasetId }: { datasetId: string }) {
  const t = useTranslations("datasets");
  const [generating, setGenerating] = useState(false);

  return (
    <div className="space-y-4">
      <Card data-tour="datasets-generate">
        <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
          <div className="min-w-0 flex-1 space-y-1.5">
            <CardTitle className="text-base">{t("generateCases")}</CardTitle>
            <CardDescription>{t("generateIntro")}</CardDescription>
          </div>
          <Button onClick={() => setGenerating(true)}>
            <Sparkles className="h-4 w-4" aria-hidden />
            {t("generateCases")}
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <ul className="grid gap-2 sm:grid-cols-2">
            {CASE_ORIGINS.map((origin) => (
              <li key={origin} className="rounded-md border px-3 py-2">
                <span className="block text-sm">{t(`origin.${origin}`)}</span>
                <span className="text-muted-foreground block text-xs">
                  {t(`sourceHint.${origin}`)}
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
      <ProposedCases datasetId={datasetId} canEdit />
      {generating && (
        <GenerateCasesDialog datasetId={datasetId} open onOpenChange={setGenerating} />
      )}
    </div>
  );
}
