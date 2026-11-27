"use client";

import { useState } from "react";
import { BadgeCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ServiceCard } from "@/components/settings/service-card";
import { Switch } from "@/components/ui";
import { useOrganizations, usePermissions } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import type { Organization } from "@/types";
import { Perm } from "@/types/permissions";

export function OrgPublicAttribution({ org }: { org: Organization }) {
  const { can } = usePermissions();
  return can(Perm.orgSettings) ? <PublicAttributionSwitch org={org} /> : null;
}

function PublicAttributionSwitch({ org }: { org: Organization }) {
  const t = useTranslations("teams");
  const tErrors = useTranslations("errors");
  const { setPublicAttribution } = useOrganizations();
  const [saving, setSaving] = useState(false);

  const change = async (enabled: boolean) => {
    setSaving(true);
    try {
      await setPublicAttribution(org.id, enabled);
      toast.success(t("publicAttributionSaved"));
    } catch (err) {
      toast.error(getErrorMessage(err, tErrors, t("publicAttributionFailed")));
    } finally {
      setSaving(false);
    }
  };

  return (
    <PublicAttributionSetting
      enabled={org.public_agenticos_attribution !== false}
      saving={saving}
      onChange={(next) => void change(next)}
    />
  );
}

export function PublicAttributionSetting({
  enabled,
  saving = false,
  onChange,
}: {
  enabled: boolean;
  saving?: boolean;
  onChange: (enabled: boolean) => void;
}) {
  const t = useTranslations("teams");
  return (
    <div data-tour="org-public-attribution">
      <ServiceCard
        icon={BadgeCheck}
        action={
          <Switch
            checked={enabled}
            disabled={saving}
            onCheckedChange={onChange}
            aria-label={t("publicAttribution")}
          />
        }
        title={t("publicAttribution")}
        description={t("publicAttributionDescription")}
      >
        <p className="text-muted-foreground text-xs leading-relaxed">
          {t("publicAttributionHint")}
        </p>
      </ServiceCard>
    </div>
  );
}
