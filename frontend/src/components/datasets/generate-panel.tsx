"use client";

import { useState } from "react";
import Link from "next/link";
import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { useCaseGenerator } from "@/hooks/use-agents";
import { useAiAssistance } from "@/hooks/use-organizations";
import { ROUTES } from "@/lib/constants";
import { CASE_ORIGINS } from "@/types/case-generation";
import { AiAssistanceNotice } from "./ai-assistance-notice";
import { GenerateCasesDialog } from "./generate-cases-dialog";
import { ProposedCases } from "./proposed-cases";

/**
 * A dataset's generated cases: what the generator drafts from, the way to ask
 * for more, and the drafts waiting for a decision.
 *
 * The four sources are named here rather than only in the dialog, so somebody
 * deciding whether to generate knows what each would draw on. With AI assistance
 * off the generator cannot run, so the panel says why and who can change it; the
 * drafts already waiting can still be decided, which calls no model. The
 * generator is an agent the organization edits like any other, so whoever may
 * edit it is pointed at its instructions.
 */
export function GeneratePanel({ datasetId }: { datasetId: string }) {
  const t = useTranslations("datasets");
  const [generating, setGenerating] = useState(false);
  const aiOn = useAiAssistance().enabled === true;
  const generator = useCaseGenerator();

  return (
    <div className="space-y-4">
      <Card data-tour="datasets-generate">
        <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
          <div className="min-w-0 flex-1 space-y-1.5">
            <CardTitle className="text-base">{t("generateCases")}</CardTitle>
            <CardDescription>{t("generateIntro")}</CardDescription>
          </div>
          <Button disabled={!aiOn} onClick={() => setGenerating(true)}>
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
          <AiAssistanceNotice body={t("generateAiOff")} />
          {generator?.can_edit === true && (
            <Link
              href={ROUTES.AGENT_DETAIL(generator.id)}
              className="text-muted-foreground hover:text-foreground inline-block text-sm underline"
            >
              {t("editGenerator")}
            </Link>
          )}
        </CardContent>
      </Card>
      <ProposedCases datasetId={datasetId} canEdit />
      {generating && (
        <GenerateCasesDialog datasetId={datasetId} open onOpenChange={setGenerating} />
      )}
    </div>
  );
}
