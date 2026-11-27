"use client";

import { Check, Circle } from "lucide-react";
import { Button } from "@/components/ui";
import { useTranslations } from "next-intl";
import { canReviewStartScope } from "@/lib/onboarding/scopes";
import { useStartScopeJourney } from "./start-scope-context";
import styles from "./start-scopes.module.css";

/** Shared stages are explicit; their completion is never inferred from a personal preference. */
export function StartScopeProgress() {
  const t = useTranslations("start.scopes");
  const journey = useStartScopeJourney();
  if (!journey) return null;
  const index = journey.scopes.findIndex((scope) => scope.scope === journey.current);
  return (
    <section className={styles.progress} aria-label={t("progress")}>
      <nav aria-label={t("stages")}>
        <ol className={styles.stages}>
          {journey.scopes.map((scope) => {
            const Icon = scope.completed ? Check : Circle;
            return (
              <li key={scope.scope}>
                <button
                  type="button"
                  aria-label={
                    scope.completed
                      ? t("stageCompleted", { stage: t(`${scope.scope}.title`) })
                      : t(`${scope.scope}.title`)
                  }
                  className={styles.stage}
                  aria-current={scope.scope === journey.current ? "step" : undefined}
                  disabled={journey.pending || !canReviewStartScope(journey.scopes, scope.scope)}
                  onClick={() => journey.select(scope.scope)}
                >
                  <Icon className={styles.stageIcon} aria-hidden />
                  <span>{t(`${scope.scope}.short`)}</span>
                </button>
              </li>
            );
          })}
        </ol>
      </nav>
      <div className={styles.heading}>
        <div>
          <strong>{t(`${journey.current}.title`)}</strong>
          {journey.scopes.some((scope) => scope.scope === journey.current && scope.completed) && (
            <span className="text-muted-foreground ml-2 text-xs">{t("completed")}</span>
          )}
          <p>{t(`${journey.current}.hint`)}</p>
        </div>
        <span>{t("position", { current: index + 1, total: journey.scopes.length })}</span>
      </div>
      {journey.continueReview && (
        <div className="bg-muted/40 mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg p-3">
          <p role="status" className="text-muted-foreground max-w-2xl text-sm">
            {t("sharedReview")}
          </p>
          <Button variant="outline" onClick={journey.continueReview} disabled={journey.pending}>
            {t("continueReview")}
          </Button>
        </div>
      )}
      {journey.failed && (
        <p role="alert" className="text-destructive text-sm">
          {t("saveFailed")}
        </p>
      )}
    </section>
  );
}
