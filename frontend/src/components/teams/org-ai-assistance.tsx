"use client";

import { useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";

import { SettingsSection } from "@/components/settings/settings-section";
import {
  AI_ASSISTANCE_ANCHOR,
  GRADING_MODEL_ANCHOR,
} from "@/components/teams/enable-ai-assistance-link";
import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { useModelProviders, useOrganizations, usePermissions } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import type { Organization } from "@/types";
import { Perm } from "@/types/permissions";

/**
 * Whether models may assist this organization's evals and authoring.
 *
 * One switch for the eval judge, the case generator and the authoring assistant,
 * and the model new judges grade on. The backend refuses those runs while it is
 * off, so this section is how a person changes it, not what enforces it. Gated on `org:settings`, matching the PATCH,
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
        <GradingModel org={org} />
      </SettingsSection>
    </div>
  );
}

/** The Select's value for no model chosen: Radix refuses an empty one. */
const AUTOMATIC = "automatic";

/**
 * The model new judges grade on, or automatic: a model that costs more than the
 * agent's each judge grades. Judges that already exist keep their model.
 */
function GradingModel({ org }: { org: Organization }) {
  const t = useTranslations("teams");
  const tErrors = useTranslations("errors");
  const { setGradingModel } = useOrganizations();
  const { profiles } = useModelProviders();
  const [saving, setSaving] = useState(false);
  const chat = profiles.filter((profile) => profile.chat_capable !== false);

  const handleChange = async (value: string) => {
    setSaving(true);
    try {
      await setGradingModel(org.id, value === AUTOMATIC ? null : value);
      toast.success(t("gradingModelSaved"));
    } catch (err) {
      toast.error(getErrorMessage(err, tErrors, t("gradingModelFailed")));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      id={GRADING_MODEL_ANCHOR}
      data-tour={GRADING_MODEL_ANCHOR}
      className="mt-4 space-y-1.5 border-t pt-4"
    >
      <Label htmlFor="org-grading-model-select">{t("gradingModel")}</Label>
      <Select
        value={org.grading_model_profile_id ?? AUTOMATIC}
        disabled={saving}
        onValueChange={(value) => void handleChange(value)}
      >
        <SelectTrigger id="org-grading-model-select" className="w-full sm:w-96">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={AUTOMATIC}>{t("gradingModelAutomatic")}</SelectItem>
          {chat.map((profile) => (
            <SelectItem key={profile.id} value={profile.id}>
              {profile.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-muted-foreground text-xs">{t("gradingModelHint")}</p>
    </div>
  );
}
