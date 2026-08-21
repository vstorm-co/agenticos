"use client";

import { useEffect } from "react";
import { Building2, ChevronsUpDown, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { useOrganizations } from "@/hooks";
import { usePathname, useRouter } from "@/lib/locale-navigation";
import { useTranslations } from "next-intl";

/**
 * The organization the whole product is scoped by, at the head of the column.
 *
 * Shaped for that one position rather than for a toolbar: full width, the name
 * unabbreviated, the active organization readable without opening anything.
 * Picking the wrong one does not produce an error - it produces the wrong
 * agents, the wrong keys and the wrong run history, all of which look exactly
 * like the right ones.
 */
export function OrgSwitcher() {
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

  const displayOrg = activeOrg ?? orgs[0];

  if (!displayOrg) {
    return (
      <Button
        variant="outline"
        className="h-auto w-full justify-start px-2 py-1.5"
        onClick={() => router.push("/orgs")}
      >
        <Building2 className="mr-2 h-4 w-4" />
        {t("selectOrg")}
      </Button>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="border-input hover:bg-accent/60 focus-visible:ring-ring flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-left transition-colors outline-none focus-visible:ring-1"
        >
          {/* Decoration: the initials are the same two letters as the name
              beside them, and read out first they bury it. */}
          <EntityAvatar
            seed={displayOrg.id}
            name={displayOrg.name}
            imageSrc={`/api/orgs/${displayOrg.id}/avatar`}
            hasImage={!!displayOrg.avatar_url}
            colorSlot={displayOrg.avatar_color}
            className="h-5 w-5 shrink-0 text-[10px]"
            ariaHidden
          />
          {/* Named for assistive technology, because "Personal" on its own does
              not say what picking it would change. */}
          <span className="sr-only">{t("organization")}</span>
          <span className="min-w-0 flex-1 truncate text-sm font-medium">{displayOrg.name}</span>
          <ChevronsUpDown className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        {orgs.map((org) => (
          <DropdownMenuItem key={org.id} onSelect={() => pick(org.id)} className="gap-2">
            <EntityAvatar
              seed={org.id}
              name={org.name}
              imageSrc={`/api/orgs/${org.id}/avatar`}
              hasImage={!!org.avatar_url}
              colorSlot={org.avatar_color}
              className="h-5 w-5 text-[10px]"
            />
            <span className="truncate">{org.name}</span>
            {org.is_personal && (
              <span className="text-muted-foreground ml-auto text-[10px]">{t("personal")}</span>
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
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
