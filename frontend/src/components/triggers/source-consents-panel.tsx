"use client";

import { useTranslations } from "next-intl";
import { useRoutineSources } from "@/hooks/use-routine-sources";
import { Button, Spinner } from "@/components/ui";
import { ErrorState } from "@/components/states/error-state";
import type { Trigger } from "@/types/triggers";

export function SourceConsentsPanel({ trigger }: { trigger: Trigger }) {
  const t = useTranslations("triggers.sourceConsents");
  const { data, isLoading, error, replace, refetch } = useRoutineSources(
    trigger.agent_id,
    trigger.id,
  );
  return (
    <section aria-label={t("title")} className="space-y-3 rounded-lg border p-3">
      <h3 className="text-sm font-medium">{t("title")}</h3>
      <p className="text-muted-foreground text-sm">{t("description")}</p>
      {isLoading ? (
        <Spinner />
      ) : error ? (
        <ErrorState cta={{ label: t("retry"), onClick: () => void refetch() }} />
      ) : (
        data && (
          <>
            <p className="text-sm">{t(data.current ? "current" : "changed")}</p>
            <ul className="max-h-44 space-y-1 overflow-y-auto text-xs break-all">
              {[...data.resources, ...data.accounts].map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
            {data.unavailable_sources.length > 0 && (
              <p role="status" className="text-sm">
                {t("unavailable", { names: data.unavailable_sources.join(", ") })}
              </p>
            )}
            <Button
              variant="outline"
              disabled={replace.isPending || data.unavailable_sources.length > 0 || data.current}
              onClick={() => replace.mutate(data.review_token)}
            >
              {t("accept")}
            </Button>
          </>
        )
      )}
    </section>
  );
}
