"use client";

import { useState } from "react";
import { Loader2, Wallet } from "lucide-react";
import { toast } from "sonner";

import { CurrencyOrganizationSwitch } from "@/components/money/currency-organization-switch";
import { useTenantId } from "@/hooks/use-organizations";
import { canonicalUsd } from "@/lib/money";
import { useMoney } from "@/components/providers/currency-provider";
import { MonetaryInput } from "@/components/money/monetary-input";
import { useMonetaryInputs } from "@/hooks/use-monetary-inputs";
import { useLocale } from "next-intl";
import { ServiceCard } from "@/components/settings/service-card";
import { Button } from "@/components/ui";
import { FormField } from "@/components/ui/form-field";
import { useOrganizations, usePermissions, useSpend } from "@/hooks";
import { submitFailure } from "@/lib/api-error";
import { Perm } from "@/types/permissions";
import type { Organization } from "@/types";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { useChanged } from "@/hooks/use-changed";
import { useTranslations } from "next-intl";

/** The field the server names in a refusal, so a message lands under the input. */
const FIELD = "monthly_budget_usd";

/** How the stored cap is shown in the input. An empty box means no ceiling. */
function asInputValue(limit: string | null): string {
  return canonicalUsd(limit);
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
  const tenant = useTenantId();
  const t = useTranslations("teams");
  if (tenant !== org.id)
    return (
      <ServiceCard
        icon={Wallet}
        action={null}
        title={t("monthlySpendingLimit")}
        description={t("ceilingWhatEveryAgent")}
      >
        <CurrencyOrganizationSwitch organizationId={org.id} />
      </ServiceCard>
    );
  // The form is a separate component so that its queries are not merely
  // ignored for someone without the permission - they are never issued. A
  // hook above this branch would still fetch, and `/spend` answers the same
  // roles this section is for. `budgets:manage` is what the PATCH actually
  // checks for this field, so it is what decides the section.
  return can(Perm.budgetsManage) ? <SpendingLimitForm org={org} /> : null;
}

function SpendingLimitForm({ org }: { org: Organization }) {
  const money = useMoney();
  const locale = useLocale();
  const tm = useTranslations("currencies");
  const monetary = useMonetaryInputs(`${org.id}|${org.monthly_budget_usd}`);
  const tErrors = useTranslations("errors");
  const t = useTranslations("teams");
  const tc = useTranslations("common");
  const { setMonthlyBudget } = useOrganizations();
  const { spend } = useSpend();

  const [value, setValue] = useState(asInputValue(org.monthly_budget_usd));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Re-seed when the stored value changes underneath - another tab, or the
  // request this form just made coming back with what the server settled on.
  // During render: an effect would show the old figure for a frame first.
  if (useChanged(`${org.id}|${org.monthly_budget_usd}`)) {
    setValue(asInputValue(org.monthly_budget_usd));
  }

  const trimmed = value.trim();
  const parsed = trimmed === "" ? null : trimmed;
  const changed = trimmed !== asInputValue(org.monthly_budget_usd) || monetary.has(FIELD);

  const handleSave = async (): Promise<boolean> => {
    // `null` is a real value here - it is how the ceiling is lifted - so the
    // only thing to reject locally is a box holding something that is not a
    // number. Everything else is the server's call.
    if (parsed !== null && !money.plan(money.inputValue(parsed))) {
      setError(t("enterAmountDollarsLeave"));
      return false;
    }
    setSaving(true);
    try {
      await setMonthlyBudget(org.id, parsed, monetary.payload({}).monetary_inputs);
      setError(null);
      monetary.reset();
      toast.success(parsed === null ? t("monthlyLimitRemoved") : t("monthlyLimitUpdated"));
      return true;
    } catch (failure) {
      const problem = submitFailure(failure, { fields: [FIELD] }, tErrors);
      setError(problem.fields[FIELD] ?? null);
      if (problem.toast) toast.error(problem.toast);
      return false;
    } finally {
      setSaving(false);
    }
  };

  useUnsavedChanges(`org-budget:${org.id}`, {
    dirty: changed,
    save: handleSave,
    discard: () => {
      monetary.reset();
      setValue(asInputValue(org.monthly_budget_usd));
      setError(null);
    },
  });

  return (
    <ServiceCard
      icon={Wallet}
      action={null}
      title={t("monthlySpendingLimit")}
      description={t("ceilingWhatEveryAgent") + t("monthNextAgentS") + t("emptyNoLimit")}
    >
      <div className="grid grid-cols-1 items-start gap-3 sm:flex sm:flex-wrap">
        <FormField
          label={tm("limitLabel", { currency: money.currency ?? "—" })}
          htmlFor="org-monthly-budget"
          error={error}
        >
          <MonetaryInput
            id="org-monthly-budget"
            monetary={monetary}
            field={FIELD}
            value={value}
            disabled={saving}
            onValueChange={(value) => {
              setValue(value);
              setError(null);
            }}
            placeholder={t("noLimit")}
          />
        </FormField>
        {changed && (
          <Button className="sm:mt-6" onClick={handleSave} disabled={saving}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : tc("save")}
          </Button>
        )}
      </div>
      <p className="text-muted-foreground mt-3 text-xs">
        {org.monthly_budget_usd === null
          ? tm("spentNoLimit", { spent: money.format(spend?.month_to_date_usd, locale) })
          : tm("spentOfLimit", {
              spent: money.format(spend?.month_to_date_usd, locale),
              limit: money.format(org.monthly_budget_usd, locale),
            })}
      </p>
    </ServiceCard>
  );
}
