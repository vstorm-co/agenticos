"use client";

import { useEffect } from "react";
import { Building2, Check, Plus } from "lucide-react";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { useOrganizations } from "@/hooks";
import { usePathname, useRouter } from "@/lib/locale-navigation";
import { useTranslations } from "next-intl";

/**
 * Picking the organization the whole product is scoped by - as menu items,
 * for whatever menu wants to carry them.
 *
 * It used to be a control of its own at the head of the column, above the
 * navigation. It is the account's tenant rather than a destination, so it now
 * sits in the account's menu at the foot of it, with the active one marked:
 * one place to answer "who am I and where am I", instead of that question
 * split across the two ends of the sidebar.
 *
 * Picking the wrong one does not produce an error - it produces the wrong
 * agents, the wrong keys and the wrong run history, all of which look exactly
 * like the right ones. So the active one is marked rather than merely listed
 * first.
 */
export function OrganizationMenuItems() {
  const t = useTranslations("teams");
  const { orgs, activeOrg, fetchOrgs, switchOrg } = useOrganizations();
  const router = useRouter();
  const pathname = usePathname();

  /**
   * Switch, and take an organization-scoped route with it.
   *
   * `/orgs/{id}/members` and `/orgs/{id}/roles` name their organization in the
   * URL, and the URL is what decides the tenant (#1032) - so setting the id and
   * staying put would leave the page acting on the organization just left. The
   * same page for the organization picked is what "switch" means here; every
   * other route is tenant-agnostic and stays where it is.
   *
   * Both hooks come from `@/lib/locale-navigation` rather than
   * `next/navigation`: its `usePathname` hands back the path without the locale
   * prefix, so the pattern below does not have to know about one, and its
   * `router` puts the prefix back - which the two pushes further down were
   * losing, sending a Polish reader to the English `/orgs`.
   */
  const pick = (id: string) => {
    switchOrg(id);
    const scoped = pathname.match(/\/orgs\/[^/]+(\/.*)?$/);
    if (scoped) router.push(`/orgs/${id}${scoped[1] ?? ""}`);
  };

  useEffect(() => {
    fetchOrgs();
  }, [fetchOrgs]);

  const activeId = (activeOrg ?? orgs[0])?.id;

  return (
    <>
      {orgs.map((org) => (
        <DropdownMenuItem key={org.id} onSelect={() => pick(org.id)} className="gap-2">
          <EntityAvatar
            seed={org.id}
            name={org.name}
            imageSrc={`/api/orgs/${org.id}/avatar`}
            hasImage={!!org.avatar_url}
            colorSlot={org.avatar_color}
            kind="org"
            className="h-5 w-5 text-[10px]"
          />
          <span className="truncate">{org.name}</span>
          {org.id === activeId ? (
            <Check className="text-muted-foreground ml-auto h-3.5 w-3.5 shrink-0" aria-hidden />
          ) : (
            org.is_personal && (
              <span className="text-muted-foreground ml-auto text-[10px]">{t("personal")}</span>
            )
          )}
        </DropdownMenuItem>
      ))}
      <DropdownMenuSeparator />
      <DropdownMenuItem onSelect={() => router.push("/orgs")} className="gap-2">
        <Building2 className="h-4 w-4" />
        {t("manageOrganizations")}
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => router.push("/orgs?create=1")} className="gap-2">
        <Plus className="h-4 w-4" />
        {t("newOrganization")}
      </DropdownMenuItem>
    </>
  );
}
