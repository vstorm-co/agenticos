"use client";

import { useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";

import { SettingsSection } from "@/components/settings/settings-section";
import { AI_ASSISTANCE_ANCHOR } from "@/components/teams/enable-ai-assistance-link";
import { Switch } from "@/components/ui";
import { useOrganizations, usePermissions } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import type { Organization } from "@/types";
import { Perm } from "@/types/permissions";

/**
 * Whether models may assist this organization's evals and authoring.
 *
 * One switch for the eval judge, the case generator and the authoring assistant.
 * The backend refuses those runs while it is off, so this section is how a person
 * changes it, not what enforces it. Gated on `org:settings`, matching the PATCH,
 * and hidden rather than disabled like the other governance sections here.
 */
export function OrgAiAssistance({ org }: { org: Organization }) {
  const { can } = usePermissions();
  return can(Perm.orgSettings) ? <AiAssistanceSwitch org={org} /> : null;
}

function AiAssistanceSwitch({ org }: { org: Organization }) {
  const t = useTranslations("teams");
  const tErrors = useTranslations("errors");
  const { setAiAssistance } = useOrganizations();
  const [saving, setSaving] = useState(false);

  const handleChange = async (enabled: boolean) => {
    setSaving(true);
    try {
      await setAiAssistance(org.id, enabled);
      toast.success(enabled ? t("aiAssistanceOn") : t("aiAssistanceOff"));
    } catch (err) {
      toast.error(getErrorMessage(err, tErrors, t("aiAssistanceFailed")));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div id={AI_ASSISTANCE_ANCHOR} data-tour={AI_ASSISTANCE_ANCHOR}>
      <SettingsSection title={t("aiAssistance")} description={t("aiAssistanceDescription")}>
        <label className="flex items-start gap-3">
          <Switch
            checked={org.ai_assistance_enabled}
            disabled={saving}
            onCheckedChange={(next) => void handleChange(next)}
            aria-label={t("aiAssistance")}
          />
          <span className="text-muted-foreground text-xs leading-relaxed">
            {t("aiAssistanceHint")}
          </span>
        </label>
      </SettingsSection>
    </div>
  );
}
