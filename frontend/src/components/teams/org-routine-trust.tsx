"use client";

import { useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";

import { SettingsSection } from "@/components/settings/settings-section";
import { Switch } from "@/components/ui";
import { useOrganizations, usePermissions } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import type { Organization } from "@/types";
import { Perm } from "@/types/permissions";

/**
 * Whether a routine here may trust its agent: use the agent's future sources and
 * tools without its creator reviewing them again.
 *
 * Off until somebody turns it on. Gated on `approvals:decide`, like the approval
 * waiver beside it and like the PATCH: it is the same kind of decision - letting
 * work go ahead that nobody reviewed - and who may then choose it per routine is
 * `approvals:decide` again, on the routine's creator.
 */
export function OrgRoutineTrust({ org }: { org: Organization }) {
  const { can } = usePermissions();
  return can(Perm.approvalsDecide) ? <TrustSwitch org={org} /> : null;
}

function TrustSwitch({ org }: { org: Organization }) {
  const t = useTranslations("teams");
  const tErrors = useTranslations("errors");
  const { setRoutinesMayTrustAgent } = useOrganizations();
  const [saving, setSaving] = useState(false);

  const handleChange = async (allowed: boolean) => {
    setSaving(true);
    try {
      await setRoutinesMayTrustAgent(org.id, allowed);
      toast.success(allowed ? t("routineTrustAllowed") : t("routineTrustForbidden"));
    } catch (err) {
      toast.error(getErrorMessage(err, tErrors, t("routineTrustFailed")));
    } finally {
      setSaving(false);
    }
  };

  return (
    <SettingsSection title={t("routineTrust")} description={t("routineTrustDescription")}>
      <label className="flex items-start gap-3">
        <Switch
          checked={org.routines_may_trust_agent === true}
          disabled={saving}
          onCheckedChange={(next) => void handleChange(next)}
          aria-label={t("routineTrust")}
        />
        <span className="text-muted-foreground text-xs leading-relaxed">
          {t("routineTrustHint")}
        </span>
      </label>
    </SettingsSection>
  );
}
