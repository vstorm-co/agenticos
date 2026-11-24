"use client";

import { useTranslations } from "next-intl";
import { Button, Switch } from "@/components/ui";
import {
  useBrowserProcedureTeachingAudience,
  useBrowserProcedureTeachingPreference,
} from "@/hooks/use-browser-procedure-teaching-settings";
import { TeachingError } from "./browser-teaching-status";

export function BrowserTeachingPreference({ agentId }: { agentId: string }) {
  const audience = useBrowserProcedureTeachingAudience();
  return (
    <PreferenceContent
      key={JSON.stringify([audience.actor, audience.organization, agentId])}
      agentId={agentId}
    />
  );
}
function PreferenceContent({ agentId }: { agentId: string }) {
  const t = useTranslations("browserProcedureTeaching");
  const preference = useBrowserProcedureTeachingPreference(agentId);
  const current = preference.data;
  return (
    <section aria-label={t("preferenceTitle")} className="space-y-2 rounded-lg border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h3 className="text-sm font-medium">{t("preferenceTitle")}</h3>
          <p className="text-muted-foreground text-xs">{t("preferenceDescription")}</p>
        </div>
        {current && (
          <Switch
            aria-label={t("preferenceTitle")}
            checked={current.enabled}
            disabled={preference.update.isPending || (!current.enabled && !current.allowed)}
            onCheckedChange={(enabled) =>
              preference.update.mutate({ generation: current.generation, enabled })
            }
          />
        )}
      </div>
      {preference.isPending && (
        <p role="status" className="text-xs">
          {t("loading")}
        </p>
      )}
      {current && !current.allowed && (
        <p className="text-muted-foreground text-xs">{t("preferenceUnavailable")}</p>
      )}
      {(preference.error || preference.update.error) && (
        <TeachingError error={preference.error || preference.update.error} />
      )}
      {preference.error && (
        <Button
          size="sm"
          variant="outline"
          onClick={() => void preference.refetch()}
          disabled={preference.isFetching}
        >
          {t("checkAgain")}
        </Button>
      )}
    </section>
  );
}
