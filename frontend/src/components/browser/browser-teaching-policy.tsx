"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { SettingsSection } from "@/components/settings/settings-section";
import { Button, ConfirmDialog, Switch } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import {
  useBrowserProcedureTeachingAudience,
  useBrowserProcedureTeachingPolicy,
} from "@/hooks/use-browser-procedure-teaching-settings";
import { Perm } from "@/types/permissions";
import { TeachingError } from "./browser-teaching-status";

export function BrowserTeachingPolicy() {
  const audience = useBrowserProcedureTeachingAudience();
  const { can } = usePermissions();
  return can(Perm.orgSettings) ? (
    <PolicyContent key={JSON.stringify([audience.actor, audience.organization])} />
  ) : null;
}
function PolicyContent() {
  const t = useTranslations("browserProcedureTeaching");
  const policy = useBrowserProcedureTeachingPolicy();
  const [confirm, setConfirm] = useState<boolean | null>(null);
  const current = policy.data;
  return (
    <div data-tour="org-browser-teaching">
      <SettingsSection title={t("policyTitle")} description={t("policyDescription")}>
        {policy.isPending ? (
          <p role="status">{t("loading")}</p>
        ) : policy.error ? (
          <TeachingError error={policy.error} />
        ) : (
          current && (
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-2 text-sm">
                <p>{t("policyDefaultOff")}</p>
                {!current.deployment_enabled && (
                  <p className="text-muted-foreground">{t("deploymentDisabled")}</p>
                )}
              </div>
              <Switch
                aria-label={t("policyTitle")}
                checked={current.enabled}
                disabled={
                  policy.update.isPending || (!current.enabled && !current.deployment_enabled)
                }
                onCheckedChange={setConfirm}
              />
            </div>
          )
        )}
        {policy.update.error && <TeachingError error={policy.update.error} />}
        {policy.error && (
          <Button
            variant="outline"
            disabled={policy.isFetching}
            onClick={() => void policy.refetch()}
          >
            {t("checkAgain")}
          </Button>
        )}
      </SettingsSection>
      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => {
          if (!open) setConfirm(null);
        }}
        title={confirm ? t("enablePolicy") : t("disablePolicy")}
        description={confirm ? t("enablePolicyDetail") : t("disablePolicyDetail")}
        confirmLabel={t("save")}
        loading={policy.update.isPending}
        onConfirm={async () => {
          if (!current || confirm === null) return;
          try {
            await policy.update.mutateAsync({ generation: current.generation, enabled: confirm });
            setConfirm(null);
          } catch {
            /* The scoped mutation renders its fixed refusal above. */
          }
        }}
      />
    </div>
  );
}
