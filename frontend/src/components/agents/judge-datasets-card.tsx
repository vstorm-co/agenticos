"use client";

import { FlaskConical } from "lucide-react";
import { useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ListCardEmpty,
} from "@/components/ui";
import { JudgeDatasetRow } from "@/components/agents/judge-dataset-row";
import { useDatasets } from "@/hooks/use-datasets";
import { useJudgeAgreement } from "@/hooks/use-scoring";
import { getErrorMessage } from "@/lib/api-error";

/** How often people agreed with the judge, once anybody decided what it graded. */
function JudgeAgreementLine({ judgeId }: { judgeId: string }) {
  const t = useTranslations("agents");
  const { agreement } = useJudgeAgreement(judgeId);
  if (agreement === undefined) return null;
  return (
    <p className="text-sm font-medium">
      {agreement.decided === 0
        ? t("judgeAgreementNone")
        : t("judgeAgreement", { agreed: agreement.agreed, decided: agreement.decided })}
    </p>
  );
}

/** As many datasets as one page of the listing holds. */
const SHOWN = 100;

/**
 * The datasets of a judge, as far as the caller may see them: the ones that
 * picked it, grading or not. Each links to its Grading tab - where a dataset
 * changes which judge it uses - and opens on what the judge graded there.
 */
export function JudgeDatasetsCard({ judgeId }: { judgeId: string }) {
  const t = useTranslations("agents");
  const tErrors = useTranslations("errors");
  const { datasets, isLoading, error } = useDatasets({ judge: judgeId, limit: SHOWN });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("judgeDatasets")}</CardTitle>
        <CardDescription>{t("judgeDatasetsHint")}</CardDescription>
        <JudgeAgreementLine judgeId={judgeId} />
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <LoadingState variant="skeleton-cards" rows={2} />
        ) : error ? (
          <ErrorState description={getErrorMessage(error, tErrors)} />
        ) : datasets.length === 0 ? (
          <ListCardEmpty icon={FlaskConical} title={t("judgeUnused")} />
        ) : (
          <ul className="divide-y">
            {datasets.map((dataset) => (
              <li key={dataset.id}>
                <JudgeDatasetRow dataset={dataset} judgeId={judgeId} />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
