"use client";

import { ExternalLink, FlaskConical } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useWorkflowExposure } from "@/hooks";
import { CopyableValue } from "./triggers/copyable-value";

export function FormLinks({
  workflowId,
  entryId,
  saving,
  canTest,
}: {
  workflowId: string;
  entryId: string;
  saving: boolean;
  canTest: boolean;
}) {
  const t = useTranslations("workflows.formPage");
  const { exposure } = useWorkflowExposure(workflowId, "trigger.form", entryId);
  return (
    <section className="bg-muted/30 space-y-3 rounded-xl border p-4">
      <p className="text-sm font-medium">{t("links")}</p>
      {canTest && (
        <Button asChild variant="outline" size="sm" disabled={saving}>
          {saving ? (
            <span>{t("saving")}</span>
          ) : (
            <a
              target="_blank"
              rel="noopener noreferrer"
              href={`/workflows/${workflowId}/form-preview?entry=${encodeURIComponent(entryId)}`}
            >
              <FlaskConical className="size-4" />
              {t("testForm")}
            </a>
          )}
        </Button>
      )}
      <p className="text-muted-foreground text-xs">{t("testHint")}</p>
      {exposure?.form_url ? (
        <div className="space-y-2">
          <CopyableValue
            id={`form-url-${entryId}`}
            label={t("publicLink")}
            value={exposure.form_url}
          />
          <Button asChild variant="ghost" size="sm">
            <a href={exposure.form_url} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="size-4" />
              {t("openPublished")}
            </a>
          </Button>
        </div>
      ) : (
        <p className="text-muted-foreground text-xs">{t("publishHint")}</p>
      )}
    </section>
  );
}
