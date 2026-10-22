"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { SettingsSection } from "@/components/settings/settings-section";
import { Button, Input } from "@/components/ui";
import { FormField } from "@/components/ui/form-field";
import { useOrganizations, usePermissions } from "@/hooks";
import { useChanged } from "@/hooks/use-changed";
import { submitFailure } from "@/lib/api-error";
import type { Organization } from "@/types";
import { Perm } from "@/types/permissions";

/** The field the server names in a refusal, so a message lands under the input. */
const FIELD = "proactive_limit_usd";

/** "1.000000" from the API reads as the "1" somebody typed. */
const asInputValue = (limit: string | undefined): string => String(Number(limit ?? "1"));

/**
 * What the platform may spend on each person a month on its own initiative (#2301):
 * noticing a request they keep repeating, writing their first messages. Per
 * person, so one busy member cannot use up everybody's; zero switches it off.
 * Gated on `budgets:manage`, like the organization's own limit beside it.
 */
export function OrgProactiveLimit({ org }: { org: Organization }) {
  const { can } = usePermissions();
  return can(Perm.budgetsManage) ? <ProactiveLimitForm org={org} /> : null;
}

function ProactiveLimitForm({ org }: { org: Organization }) {
  const t = useTranslations("teams.proactive");
  const tErrors = useTranslations("errors");
  const { setProactiveLimit } = useOrganizations();
  const [value, setValue] = useState(asInputValue(org.proactive_limit_usd));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  if (useChanged(`${org.id}|${org.proactive_limit_usd}`)) {
    setValue(asInputValue(org.proactive_limit_usd));
  }

  const parsed = Number(value.trim());
  const changed = value.trim() !== asInputValue(org.proactive_limit_usd);

  const save = async () => {
    if (value.trim() === "" || !Number.isFinite(parsed) || parsed < 0) {
      setError(t("invalid"));
      return;
    }
    setSaving(true);
    try {
      await setProactiveLimit(org.id, parsed);
      setError(null);
      toast.success(parsed === 0 ? t("off") : t("saved"));
    } catch (failure) {
      const problem = submitFailure(failure, { fields: [FIELD] }, tErrors);
      setError(problem.fields[FIELD] ?? null);
      if (problem.toast) toast.error(problem.toast);
    } finally {
      setSaving(false);
    }
  };

  return (
    <SettingsSection title={t("title")} description={t("description")}>
      <div className="flex flex-wrap items-start gap-3">
        <FormField label={t("label")} htmlFor="org-proactive-limit" error={error}>
          <Input
            id="org-proactive-limit"
            type="number"
            min="0"
            step="0.5"
            value={value}
            disabled={saving}
            onChange={(event) => {
              setValue(event.target.value);
              setError(null);
            }}
          />
        </FormField>
        {changed && (
          <Button className="mt-6" onClick={save} disabled={saving}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : t("save")}
          </Button>
        )}
      </div>
    </SettingsSection>
  );
}
