"use client";

import { Building2, ChevronsUpDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { OrganizationMenuItems } from "@/components/teams/org-switcher";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { useOrganizations } from "@/hooks";
import { cn } from "@/lib/utils";

/** The tenant stays visible above navigation, even when the destinations scroll. */
export function OrganizationSwitcher({
  collapsed = false,
  onNavigate,
}: {
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const t = useTranslations("teams");
  const { activeOrg } = useOrganizations();
  const label = activeOrg
    ? t("organizationSwitcher", { name: activeOrg.name })
    : t("selectOrganization");

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          data-tour="organization-switcher"
          aria-label={label}
          title={label}
          className={cn(
            "hover:bg-control-hover focus-visible:ring-ring data-[state=open]:bg-control touch:min-h-11 touch:min-w-11 flex items-center rounded-xl text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-inset",
            collapsed ? "size-10 justify-center" : "h-10 w-full gap-2.5 px-2.5",
          )}
        >
          {activeOrg ? (
            <EntityAvatar
              seed={activeOrg.id}
              name={activeOrg.name}
              imageSrc={`/api/orgs/${activeOrg.id}/avatar?v=${activeOrg.updated_at ?? ""}`}
              hasImage={!!activeOrg.avatar_url}
              colorSlot={activeOrg.avatar_color}
              size="sm"
              className="shrink-0"
              ariaHidden
            />
          ) : (
            <Building2 className="text-muted-foreground size-7 shrink-0 p-1" aria-hidden />
          )}
          {!collapsed && (
            <>
              <span className="min-w-0 flex-1">
                <span className="sr-only">{t("organizationLabel")}</span>
                <span className="block truncate text-sm font-medium">
                  {activeOrg?.name ?? t("selectOrganization")}
                </span>
              </span>
              <ChevronsUpDown className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
            </>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        side={collapsed ? "right" : "bottom"}
        align="start"
        sideOffset={8}
        className="w-68 p-1.5 [&_[role=separator]]:opacity-60"
      >
        <DropdownMenuLabel className="text-muted-foreground text-xs font-medium">
          {t("organizationLabel")}
        </DropdownMenuLabel>
        <OrganizationMenuItems onNavigate={onNavigate} />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
