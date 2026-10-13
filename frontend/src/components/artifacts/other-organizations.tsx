"use client";

import { Building2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { OrganizationMenuItems } from "@/components/teams";
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from "@/components/ui";
import { useOrganizations } from "@/hooks";

/**
 * The way into another organization, under "not available".
 *
 * Every request is scoped to the organization last used, and an artifact in
 * another one answers 404 like one that is gone - so a member of two who
 * follows a link without `?org=` lands here. The dashboard left the switcher in
 * its sidebar for that; this page has no sidebar, so it offers the switcher
 * itself, and only to somebody who has another organization to switch to.
 */
export function OtherOrganizations() {
  const t = useTranslations("artifacts");
  const { orgs } = useOrganizations();
  if (orgs.length < 2) return null;
  return (
    <div className="flex flex-col items-center gap-2 text-center">
      <p className="text-muted-foreground text-sm">{t("maybeOtherOrganization")}</p>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm">
            <Building2 className="h-3.5 w-3.5" />
            {t("switchOrganization")}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="center" className="w-64">
          <OrganizationMenuItems />
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
