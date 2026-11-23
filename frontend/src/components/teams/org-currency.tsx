"use client";

import { useTranslations } from "next-intl";
import { useOrganizationCurrency } from "@/hooks/use-currencies";
import { usePermissions } from "@/hooks/use-permissions";
import { SettingsSection } from "@/components/settings/settings-section";
import {
  Button,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ErrorState } from "@/components/states";
import { Perm } from "@/types/permissions";
import type { Organization } from "@/types";

export function OrgCurrency({ org }: { org: Organization }) {
  const { can } = usePermissions();
  return can(Perm.orgSettings) ? <CurrencyForm org={org} /> : null;
}

function CurrencyForm({ org }: { org: Organization }) {
  const t = useTranslations("currencies");
  const { context, save } = useOrganizationCurrency(org.id);
  const data = context.data;
  if (context.isError)
    return (
      <ErrorState
        title={t("loadFailed")}
        cta={{ label: t("retry"), onClick: () => void context.refetch() }}
      />
    );
  return (
    <SettingsSection title={t("organization")} description={t("organizationHint")}>
      <Select
        value={org.currency ?? "inherit"}
        disabled={!data || save.isPending}
        onValueChange={(value) => save.mutate(value === "inherit" ? null : value)}
      >
        <SelectTrigger aria-label={t("organization")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="inherit">
            {t("inherit", { currency: data?.default_currency ?? "USD" })}
          </SelectItem>
          {Object.keys(data?.rates ?? {}).map((currency) => (
            <SelectItem value={currency} key={currency}>
              {currency}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {save.isError && (
        <p className="text-destructive text-sm" role="alert">
          {t("saveFailed")}{" "}
          <Button variant="link" onClick={() => save.reset()}>
            {t("retry")}
          </Button>
        </p>
      )}
    </SettingsSection>
  );
}
