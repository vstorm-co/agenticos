"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { SettingsSection } from "@/components/settings/settings-section";
import { Button, Input } from "@/components/ui";
import { FormField } from "@/components/ui/form-field";
import { useOrganizations, usePermissions, useSpend } from "@/hooks";
import { submitFailure } from "@/lib/api-error";
import { Perm } from "@/types/permissions";
import type { Organization } from "@/types";

/** The field the server names in a refusal, so a message lands under the input. */
const FIELD = "monthly_budget_usd";

/** How the stored cap is shown in the input. An empty box means no ceiling. */
function asInputValue(limit: number | null): string {
  return limit === null ? "" : String(limit);
}

/**
 * The organization's monthly spending ceiling.
 *
 * The limit over every agent in the workspace, as opposed to the per-agent one
 * in the Builder. Without it an organization with twelve agents has twelve
 * independent caps and no ceiling - each one right, and the bill twelve times
 * what anybody agreed to.
 *
 * Rendered only for someone who may change organization settings. The whole
 * section is hidden rather than disabled, because the spend figure beside the
 * input comes from an endpoint the same roles can read: a section that could
 * only report a refusal is worse than no section.
 */
export function OrgSpendingLimit({ org }: { org: Organization }) {
  const { can } = usePermissions();
  // The form is a separate component so that its queries are not merely
  // ignored for someone without the permission - they are never issued. A
  // hook above this branch would still fetch, and `/spend` answers the same
  // roles this section is for. `budgets:manage` is what the PATCH actually
  // checks for this field, so it is what decides the section.
  return can(Perm.budgetsManage) ? <SpendingLimitForm org={org} /> : null;
}

function SpendingLimitForm({ org }: { org: Organization }) {
  const { setMonthlyBudget } = useOrganizations();
  const { spend } = useSpend();

  const [value, setValue] = useState(asInputValue(org.monthly_budget_usd));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Re-seed when the stored value changes underneath - another tab, or the
  // request this form just made coming back with what the server settled on.
  useEffect(() => {
    setValue(asInputValue(org.monthly_budget_usd));
  }, [org.id, org.monthly_budget_usd]);

  const trimmed = value.trim();
  const parsed = trimmed === "" ? null : Number(trimmed);
  const changed = trimmed !== asInputValue(org.monthly_budget_usd);
  const monthToDate = Number(spend?.month_to_date_usd ?? 0);

  const handleSave = async () => {
    // `null` is a real value here - it is how the ceiling is lifted - so the
    // only thing to reject locally is a box holding something that is not a
    // number. Everything else is the server's call.
    if (parsed !== null && !Number.isFinite(parsed)) {
      setError("Enter an amount in dollars, or leave it empty for no limit.");
      return;
    }
    setSaving(true);
    try {
      await setMonthlyBudget(org.id, parsed);
      setError(null);
      toast.success(parsed === null ? "Monthly limit removed" : "Monthly limit updated");
    } catch (failure) {
      const problem = submitFailure(failure, { fields: [FIELD] });
      setError(problem.fields[FIELD] ?? null);
      if (problem.toast) toast.error(problem.toast);
    } finally {
      setSaving(false);
    }
  };

  return (
    <SettingsSection
      title="Monthly spending limit"
      description={
        "The ceiling on what every agent in this workspace can spend between the first of the " +
        "month and the next. An agent's own limit can tighten it, never loosen it. Leave it " +
        "empty for no limit."
      }
    >
      <div className="flex flex-wrap items-start gap-3">
        <FormField label="Limit (USD)" htmlFor="org-monthly-budget" error={error}>
          <Input
            id="org-monthly-budget"
            type="number"
            min="0"
            step="1"
            value={value}
            disabled={saving}
            onChange={(event) => {
              setValue(event.target.value);
              setError(null);
            }}
            placeholder="No limit"
          />
        </FormField>
        {changed && (
          <Button className="mt-6" onClick={handleSave} disabled={saving}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}
          </Button>
        )}
      </div>
      <p className="text-foreground/55 mt-3 text-xs">
        {org.monthly_budget_usd === null
          ? `$${monthToDate.toFixed(2)} spent this month, against no limit.`
          : `$${monthToDate.toFixed(2)} of $${Number(org.monthly_budget_usd).toFixed(2)} spent this month.`}
      </p>
    </SettingsSection>
  );
}
