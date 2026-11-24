"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { SectionCard } from "@/components/settings/settings-section";
import { Label, Switch } from "@/components/ui";
import { useOrganizations } from "@/hooks";
import { useSaveProactiveOptOut } from "@/hooks/use-account-profile";
import { getErrorMessage } from "@/lib/api-error";
import { useAuthStore } from "@/stores";

/** Personal delivery preference; history and restoring dismissed items stay in Inbox → Done. */
export function YourSuggestions() {
  const t = useTranslations("assistantSettings.suggestions");
  const tErrors = useTranslations("errors");
  const optedOut = useAuthStore((state) => state.user?.proactive_opt_out ?? false);
  const saveOptOut = useSaveProactiveOptOut();
  const { activeOrg } = useOrganizations();
  const [saving, setSaving] = useState(false);
  const save = async (enabled: boolean) => {
    setSaving(true);
    try {
      await saveOptOut(!enabled);
      toast.success(enabled ? t("turnedOn") : t("turnedOff"));
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    } finally {
      setSaving(false);
    }
  };
  return (
    <SectionCard title={t("title")} description={t("description")}>
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <Label htmlFor="suggestions-for-me">{t("forMe")}</Label>
          {activeOrg?.proactive_enabled === false && (
            <p className="text-muted-foreground text-sm">{t("orgOff")}</p>
          )}
        </div>
        <Switch
          id="suggestions-for-me"
          checked={!optedOut}
          disabled={saving}
          onCheckedChange={save}
        />
      </div>
    </SectionCard>
  );
}
