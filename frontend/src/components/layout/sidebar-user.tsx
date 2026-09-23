"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { ChevronsUpDown, LogOut, UserCircle } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EntityAvatar,
} from "@/components/ui";
import { useAuth } from "@/hooks";
import { cn } from "@/lib/utils";
import { ROUTES } from "@/lib/constants";
import { AppearanceMenu, LanguageMenu } from "@/components/layout/account-preferences";
import { OrganizationMenuItems } from "@/components/teams";
import { useAuthStore } from "@/stores";

/**
 * Who is signed in, and the way out - at the foot of the column.
 *
 * Last, because it is the least-used control here and because every comparable
 * product puts it there: people look down for it. It is pinned rather than
 * scrolled with the destinations, so a long nav can never push signing out off
 * the screen.
 *
 * The name and the address are on the trigger rather than inside the menu. The
 * column has the width for them, and "which account is this" is a question
 * worth answering without a click on a platform where the answer decides what
 * every request is allowed to do.
 *
 * `compact` is the collapsed rail, where it does not: the avatar alone opens
 * the same menu, and the name and address are the first thing inside it rather
 * than gone.
 */
export function SidebarUser({ compact = false }: { compact?: boolean }) {
  const { user, logout } = useAuth();
  const avatarVersion = useAuthStore((s) => s.avatarVersion);
  const t = useTranslations("nav");

  // Everything below this component sits inside `AuthGuard`, which holds the
  // page back until /auth/me answers - so a missing user is the moment before
  // the guard resolves, not a signed-out visitor to offer a login button to.
  if (!user) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={compact ? user.full_name || user.email : undefined}
          title={compact ? user.email : undefined}
          className={cn(
            "hover:bg-accent/60 focus-visible:ring-ring flex items-center rounded-md text-left transition-colors outline-none focus-visible:ring-1",
            compact ? "h-9 w-9 justify-center" : "w-full gap-2.5 px-2 py-1.5",
          )}
        >
          {/* Decoration: the initials repeat the address underneath, and read
              out first they bury the name they abbreviate. */}
          <EntityAvatar
            seed={user.id}
            name={user.full_name || user.email}
            imageSrc={`/api/users/avatar/${user.id}?v=${avatarVersion}`}
            hasImage={!!user.avatar_url}
            colorSlot={user.avatar_color}
            size="xs"
            className="shrink-0"
            ariaHidden
          />
          {compact ? null : (
            <>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">
                  {user.full_name || user.email.split("@")[0]}
                </span>
                <span className="text-muted-foreground block truncate text-xs">{user.email}</span>
              </span>
              <ChevronsUpDown className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
            </>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-56">
        {/* On the rail the trigger is an avatar, so the menu is the only place
            the account is named at all. */}
        {compact ? (
          <>
            <div className="px-2 py-1.5">
              <p className="truncate text-sm font-medium">
                {user.full_name || user.email.split("@")[0]}
              </p>
              <p className="text-muted-foreground truncate text-xs">{user.email}</p>
            </div>
            <DropdownMenuSeparator />
          </>
        ) : null}
        {/* The tenant, above the account's own entries: every request this
            person makes is scoped by it, and it used to live at the far end of
            the column from the name it belongs to. */}
        <OrganizationMenuItems />
        <DropdownMenuSeparator />
        {/* How this looks and what language it is in. They were two unlabelled
            glyphs in a strip at the foot of the column; here they are named,
            each showing its current value, in the menu that already answers
            "who am I and how do I want this". */}
        <AppearanceMenu />
        <LanguageMenu />
        <DropdownMenuSeparator />
        {/* One entry, not two. `/profile` redirects to `/settings/profile` and
            `/settings` opens on the same tab, so the menu offered a choice
            between two labels for one destination - which reads as two places
            until you click both. */}
        <DropdownMenuItem asChild>
          <Link href={ROUTES.SETTINGS_PROFILE}>
            <UserCircle className="mr-2 h-4 w-4" />
            {t("profileAndSettings")}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={logout} className="text-destructive focus:text-destructive">
          <LogOut className="mr-2 h-4 w-4" />
          {t("logout")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
