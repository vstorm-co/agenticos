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
 * Whether a chat session here may waive this organization's approvals.
 *
 * The ceiling on `ApprovalMode.APPROVE_ALL` (#925). A standing consent is the
 * decision the approval queue exists to record, and without an organization-level
 * switch a Builder's deliberate gate on `send_email` is one click from nothing in
 * every conversation - which makes the whole per-tool approval model advisory.
 *
 * Off until somebody turns it on, so an upgrade changes nobody's behaviour. Who
 * may then waive is `approvals:decide` on the person doing it, checked again
 * server-side on every turn: this switch says whether anybody here may, never
 * who.
 *
 * Gated on `approvals:decide` rather than on `org:settings`, matching the PATCH:
 * raising the ceiling on standing consent is a decision about the approval queue,
 * and somebody who may not decide one approval should not be able to switch the
 * queue off for every conversation. Hidden rather than disabled, like the
 * spending limit beside it - a section that could only report a refusal is worse
 * than no section.
 */
export function OrgApprovalWaiver({ org }: { org: Organization }) {
  const { can } = usePermissions();
  return can(Perm.approvalsDecide) ? <WaiverSwitch org={org} /> : null;
}

function WaiverSwitch({ org }: { org: Organization }) {
  const t = useTranslations("teams");
  const tErrors = useTranslations("errors");
  const { setChatApprovalWaiver } = useOrganizations();
  const [saving, setSaving] = useState(false);

  const handleChange = async (allowed: boolean) => {
    setSaving(true);
    try {
      await setChatApprovalWaiver(org.id, allowed);
      toast.success(allowed ? t("waiverAllowed") : t("waiverForbidden"));
    } catch (err) {
      toast.error(getErrorMessage(err, tErrors, t("waiverFailed")));
    } finally {
      setSaving(false);
    }
  };

  return (
    <SettingsSection title={t("approvalWaiver")} description={t("approvalWaiverDescription")}>
      <label className="flex items-start gap-3">
        <Switch
          checked={org.chat_may_waive_approvals}
          disabled={saving}
          onCheckedChange={(next) => void handleChange(next)}
          aria-label={t("approvalWaiver")}
        />
        <span className="text-muted-foreground text-xs leading-relaxed">
          {t("approvalWaiverHint")}
        </span>
      </label>
    </SettingsSection>
  );
}
