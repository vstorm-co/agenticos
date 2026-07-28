"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { ChevronsUpDown, LogOut, Settings, UserCircle } from "lucide-react";

import {
  Avatar,
  AvatarFallback,
  AvatarImage,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";
import { useAuth } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { useAuthStore } from "@/stores";

/**
 * Who is signed in, and the way out — at the foot of the column.
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
 */
export function SidebarUser() {
  const { user, logout } = useAuth();
  const avatarVersion = useAuthStore((s) => s.avatarVersion);
  const t = useTranslations("nav");

  // Everything below this component sits inside `AuthGuard`, which holds the
  // page back until /auth/me answers — so a missing user is the moment before
  // the guard resolves, not a signed-out visitor to offer a login button to.
  if (!user) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="hover:bg-accent/60 focus-visible:ring-ring flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors outline-none focus-visible:ring-1"
        >
          {/* Decoration: the initials repeat the address underneath, and read
              out first they bury the name they abbreviate. */}
          <Avatar aria-hidden className="h-6 w-6 shrink-0">
            {user.avatar_url && (
              <AvatarImage src={`/api/users/avatar/${user.id}?v=${avatarVersion}`} alt="" />
            )}
            <AvatarFallback className="bg-foreground text-background text-[10px] font-semibold">
              {user.email.substring(0, 2).toUpperCase()}
            </AvatarFallback>
          </Avatar>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">
              {user.full_name || user.email.split("@")[0]}
            </span>
            <span className="text-muted-foreground block truncate text-xs">{user.email}</span>
          </span>
          <ChevronsUpDown className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-56">
        <DropdownMenuItem asChild>
          <Link href={ROUTES.PROFILE}>
            <UserCircle className="mr-2 h-4 w-4" />
            {t("profile")}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href={ROUTES.SETTINGS}>
            <Settings className="mr-2 h-4 w-4" />
            {t("settings")}
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
