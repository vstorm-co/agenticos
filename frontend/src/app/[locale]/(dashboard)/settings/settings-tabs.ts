import { Bell, Shield, Slash, UserCircle } from "lucide-react";

import type { PageTab } from "@/components/dashboard/page-tabs";
import { ROUTES } from "@/lib/constants";

/**
 * The tabs, and the whole of what `/settings/` holds.
 *
 * `/settings/` is *your* configuration: your profile, your account, your
 * notifications, your slash commands, and the MCP connections that carry your
 * credentials. Anything the organization owns - the provider keys it runs on,
 * the MCP servers its agents are built on - is a primary destination in the
 * sidebar and lives at the top level, so no page is claimed by two navigations
 * at once.
 *
 * Hence "Your connections" rather than "Integrations". The word that has to
 * appear in the label is the owner: the sidebar has an MCP page too, and until
 * one of them said "your" and the other said "organization", the difference
 * between them was invisible.
 *
 * This list is therefore an index of the section, not a selection from it, and
 * `settings-tabs.test.ts` fails if the two ever disagree: adding a page here
 * without a tab is how AI providers and MCP servers came to be reachable only
 * by typing their URL.
 *
 * It sits beside `layout.tsx` rather than in it because a route file may export
 * nothing but the route - `next build` rejects the extra export - and this
 * table has to be readable by the test that guards it.
 */
export const SETTINGS_TABS: readonly PageTab[] = [
  { label: "Profile", href: ROUTES.SETTINGS_PROFILE, icon: UserCircle },
  { label: "Account", href: ROUTES.SETTINGS_ACCOUNT, icon: Shield },
  { label: "Slash commands", href: ROUTES.SETTINGS_SLASH_COMMANDS, icon: Slash },
  { label: "Notifications", href: ROUTES.SETTINGS_NOTIFICATIONS, icon: Bell },
];
