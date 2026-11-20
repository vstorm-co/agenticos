"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { ChevronsUpDown, Compass, LogOut, UserCircle } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EntityAvatar,
} from "@/components/ui";
import { DesktopSetupMenuItem } from "@/components/desktop/desktop-setup-menu-item";
import { ServerSwitch } from "@/components/desktop/server-switch";
import { useAuth } from "@/hooks";
import { cn } from "@/lib/utils";
import { ROUTES } from "@/lib/constants";
import { AppearanceMenu, LanguageMenu } from "@/components/layout/account-preferences";
import { hasLocaleChoice } from "@/lib/locales";
import { useAuthStore } from "@/stores";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";

/**
 * Who is signed in, and the way out - at the foot of the column.
 *
 * Last, because it is the least-used control here and because every comparable
 * product puts it there: people look down for it. It is pinned rather than
 * scrolled with the destinations, so a long nav can never push signing out off
 * the screen.
 *
 * The name and the address are on the trigger as well as inside the menu. The
 * column has the width for them, and "which account is this" is a question
 * worth answering without a click on a platform where the answer decides what
 * every request is allowed to do.
 *
 * `compact` is the collapsed rail, where it does not: the avatar alone opens
 * the same menu. Its identity header keeps the account visible on either layout.
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
            "hover:bg-control-hover data-[state=open]:bg-control focus-visible:ring-ring flex items-center rounded-lg text-left transition-colors outline-none focus-visible:ring-2",
            compact
              ? "touch:min-h-11 touch:min-w-11 h-9 w-9 justify-center"
              : "w-full gap-2.5 px-2 py-1.5",
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
      <DropdownMenuContent
        side="top"
        align="start"
        sideOffset={8}
        collisionPadding={12}
        className="w-68 p-1.5 [&_[role=menuitem]]:min-h-9 [&_[role=separator]]:opacity-60"
      >
        <div className="flex min-w-0 items-center gap-3 px-2.5 py-3">
          <EntityAvatar
            seed={user.id}
            name={user.full_name || user.email}
            imageSrc={`/api/users/avatar/${user.id}?v=${avatarVersion}`}
            hasImage={!!user.avatar_url}
            colorSlot={user.avatar_color}
            size="sm"
            className="shrink-0"
            ariaHidden
          />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium" title={user.full_name || user.email}>
              {user.full_name || user.email.split("@")[0]}
            </p>
            <p className="text-muted-foreground truncate text-xs" title={user.email}>
              {user.email}
            </p>
          </div>
        </div>
        <DropdownMenuSeparator />
        {/* How this looks and what language it is in. Both were unlabelled
            glyphs in a strip at the foot of the column; here they are named,
            each showing its current value, in the menu that already answers
            "who am I and how do I want this". */}
        <AppearanceMenu />
        {hasLocaleChoice ? <LanguageMenu /> : null}
        <DropdownMenuSeparator />
        {/* One entry, not two. `/profile` redirects to `/settings/profile` and
            `/settings` opens on the same tab, so the menu offered a choice
            between two labels for one destination - which reads as two places
            until you click both. */}
        <DropdownMenuItem asChild>
          <Link href={ROUTES.SETTINGS_PROFILE}>
            <UserCircle className="h-4 w-4" />
            {t("profileAndSettings")}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href={ROUTES.ONBOARDING}>
            <Compass className="mr-2 h-4 w-4" aria-hidden />
            {t("onboarding")}
          </Link>
        </DropdownMenuItem>
        <DesktopSetupMenuItem />
        <ServerSwitch />
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={() => useUnsavedChangesStore.getState().leave(() => void logout())}
          className="text-muted-foreground focus:text-foreground"
        >
          <LogOut className="h-4 w-4" />
          {t("logout")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
