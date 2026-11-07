"use client";

import { useEffect } from "react";
import { Building2, Check, Plus } from "lucide-react";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { useOrganizations } from "@/hooks";
import { usePathname, useRouter } from "@/lib/locale-navigation";
import { useTranslations } from "next-intl";

/**
 * The organization switcher's choices and management actions.
 *
 * Picking the wrong one does not produce an error - it produces the wrong
 * agents, the wrong keys and the wrong run history, all of which look exactly
 * like the right ones. So the active one is marked rather than merely listed
 * first.
 */
export function OrganizationMenuItems({ onNavigate }: { onNavigate?: () => void }) {
  const t = useTranslations("teams");
  const { orgs, activeOrg, fetchOrgs, switchOrg } = useOrganizations();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    void fetchOrgs();
  }, [fetchOrgs]);

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
    if (id !== activeOrg?.id) switchOrg(id);
    const scoped = pathname.match(/\/orgs\/[^/]+(\/.*)?$/);
    if (scoped) {
      const destination = `/orgs/${id}${scoped[1] ?? ""}`;
      if (pathname !== destination) router.push(destination);
    }
    onNavigate?.();
  };

  const navigate = (href: string) => {
    router.push(href);
    onNavigate?.();
  };

  return (
    <>
      <div className="max-h-64 overflow-y-auto overscroll-contain">
        {orgs.map((org) => (
          <DropdownMenuItem
            key={org.id}
            onSelect={() => pick(org.id)}
            className="gap-2"
            aria-current={org.id === activeOrg?.id ? "true" : undefined}
          >
            <EntityAvatar
              seed={org.id}
              name={org.name}
              imageSrc={`/api/orgs/${org.id}/avatar?v=${org.updated_at ?? ""}`}
              hasImage={!!org.avatar_url}
              colorSlot={org.avatar_color}
              className="h-5 w-5 text-[11px]"
              ariaHidden
            />
            <span className="truncate">{org.name}</span>
            {org.is_personal && (
              <span className="text-muted-foreground ml-auto text-xs">{t("personal")}</span>
            )}
            {org.id === activeOrg?.id && (
              <Check className="text-muted-foreground ml-auto h-3.5 w-3.5 shrink-0" aria-hidden />
            )}
          </DropdownMenuItem>
        ))}
      </div>
      <DropdownMenuSeparator />
      <DropdownMenuItem onSelect={() => navigate("/orgs")} className="gap-2">
        <Building2 className="h-4 w-4" aria-hidden />
        {t("manageOrganizations")}
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => navigate("/orgs?create=1")} className="gap-2">
        <Plus className="h-4 w-4" aria-hidden />
        {t("newOrganization")}
      </DropdownMenuItem>
    </>
  );
}
