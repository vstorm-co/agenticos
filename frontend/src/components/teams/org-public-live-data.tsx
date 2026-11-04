"use client";

import { useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";

import { SettingsSection } from "@/components/settings/settings-section";
import { ConfirmDialog, Switch } from "@/components/ui";
import { useOrganizations, usePermissions } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import type { Organization } from "@/types";
import { Perm } from "@/types/permissions";

/**
 * Whether a page's data may reach people with no account (#1975).
 *
 * A published page can read table records. Members see them under their own
 * consent; this is the ceiling for anonymous visitors of a page's public link and
 * for the sites that embed it. Off until an Owner or Admin turns it on, so an
 * upgrade shares nothing new; even on, each page still needs its owner's own
 * confirmation, which this switch neither gives nor takes away. Turning it off
 * cuts the data from every public page at once and keeps the confirmations, so
 * turning it on again restores the pages that were confirmed.
 *
 * Gated on `org:settings`, matching the PATCH, and hidden rather than disabled.
 * Turning it on asks first, since it widens who reads records; turning it off
 * narrows and does not.
 */
export function OrgPublicLiveData({ org }: { org: Organization }) {
  const { can } = usePermissions();
  return can(Perm.orgSettings) ? <PublicLiveDataSwitch org={org} /> : null;
}

function PublicLiveDataSwitch({ org }: { org: Organization }) {
  const t = useTranslations("teams");
  const tErrors = useTranslations("errors");
  const { setPublicLiveData } = useOrganizations();
  const [saving, setSaving] = useState(false);
  const [asking, setAsking] = useState(false);

  const change = async (allowed: boolean) => {
    setSaving(true);
    try {
      await setPublicLiveData(org.id, allowed);
      toast.success(allowed ? t("publicLiveDataOn") : t("publicLiveDataOff"));
      setAsking(false);
    } catch (err) {
      toast.error(getErrorMessage(err, tErrors, t("publicLiveDataFailed")));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div data-tour="org-public-live-data">
      <SettingsSection title={t("publicLiveData")} description={t("publicLiveDataDescription")}>
        <label className="flex items-start gap-3">
          <Switch
            checked={org.public_live_data}
            disabled={saving}
            onCheckedChange={(next) => (next ? setAsking(true) : void change(false))}
            aria-label={t("publicLiveData")}
          />
          <span className="text-muted-foreground text-xs leading-relaxed">
            {t("publicLiveDataHint")}
          </span>
        </label>
      </SettingsSection>
      <ConfirmDialog
        open={asking}
        onOpenChange={setAsking}
        title={t("publicLiveDataConfirmTitle")}
        description={t("publicLiveDataConfirmWhy")}
        confirmLabel={t("publicLiveDataConfirm")}
        loading={saving}
        onConfirm={() => void change(true)}
      />
    </div>
  );
}
