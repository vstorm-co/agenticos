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
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useOrganizations } from "@/hooks";
import { useRouter } from "next/navigation";

/**
 * The organization the whole product is scoped by, at the head of the column.
 *
 * Shaped for that one position rather than for a toolbar: full width, the name
 * unabbreviated, the active organization readable without opening anything.
 * Picking the wrong one does not produce an error — it produces the wrong
 * agents, the wrong keys and the wrong run history, all of which look exactly
 * like the right ones.
 */
export function OrgSwitcher() {
  const { orgs, activeOrg, fetchOrgs, switchOrg } = useOrganizations();
  const router = useRouter();

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
        Select org
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
          <Avatar aria-hidden className="h-5 w-5 shrink-0">
            {displayOrg.avatar_url && <AvatarImage src={`/api/orgs/${displayOrg.id}/avatar`} />}
            <AvatarFallback className="text-[10px]">
              {displayOrg.name.substring(0, 2).toUpperCase()}
            </AvatarFallback>
          </Avatar>
          {/* Named for assistive technology, because "Personal" on its own does
              not say what picking it would change. */}
          <span className="sr-only">Organization:</span>
          <span className="min-w-0 flex-1 truncate text-sm font-medium">{displayOrg.name}</span>
          <ChevronsUpDown className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        {orgs.map((org) => (
          <DropdownMenuItem key={org.id} onSelect={() => switchOrg(org.id)} className="gap-2">
            <Avatar className="h-5 w-5">
              {org.avatar_url && <AvatarImage src={`/api/orgs/${org.id}/avatar`} />}
              <AvatarFallback className="text-[10px]">
                {org.name.substring(0, 2).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <span className="truncate">{org.name}</span>
            {org.is_personal && (
              <span className="text-muted-foreground ml-auto text-[10px]">Personal</span>
            )}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => router.push("/orgs")} className="gap-2">
          <Building2 className="h-4 w-4" />
          Manage organizations
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => router.push("/orgs?create=1")} className="gap-2">
          <Plus className="h-4 w-4" />
          New organization
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
