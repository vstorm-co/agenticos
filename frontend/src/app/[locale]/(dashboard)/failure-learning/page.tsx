"use client";

import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { PatternsPanel } from "@/components/failure-learning/patterns-panel";
import { useOrgPatterns } from "@/hooks/use-failure-learning";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";

/**
 * The org-wide patterns page: every agent's recurring failures in the last
 * 7 days, and the model-scoped patterns that follow a model from agent to
 * agent. Tracking a pattern curates it into its agent's ledger, where the
 * rest of the work happens. Gated on `runs:view` in the nav and by the
 * route itself.
 */
export default function FailureLearningPage() {
  const t = useTranslations("failureLearning");
  const { can } = usePermissions();
  const { patterns, isLoading, error, track } = useOrgPatterns();

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} description={t("description")} />
      <section className="space-y-3">
        <h2 className="text-base font-semibold">{t("patterns")}</h2>
        <p className="text-muted-foreground text-sm">{t("patternsDescription")}</p>
        <PatternsPanel
          patterns={patterns}
          isLoading={isLoading}
          error={error}
          canTrack={can(Perm.agentsEdit)}
          onTrack={(pattern, input) => track.mutate({ pattern, input })}
        />
      </section>
    </div>
  );
}
