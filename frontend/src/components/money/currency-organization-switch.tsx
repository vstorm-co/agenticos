"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { useOrganizations } from "@/hooks/use-organizations";

/** Keep permission, spend and quote contexts on the same organization. */
export function CurrencyOrganizationSwitch({ organizationId }: { organizationId: string }) {
  const t = useTranslations("currencies");
  const { switchOrg } = useOrganizations();
  return (
    <div className="space-y-3">
      <p className="text-muted-foreground text-sm">{t("switchOrganizationHint")}</p>
      <Button onClick={() => void switchOrg(organizationId)}>{t("switchOrganization")}</Button>
    </div>
  );
}
