import { Activity, Building2, LayoutDashboard, MessageSquare, Settings, Users } from "lucide-react";

import type { PageTab } from "@/components/dashboard/page-tabs";
import { ROUTES } from "@/lib/constants";

/**
 * The tabs, and the whole of what `/admin/` holds.
 *
 * Beside the layout rather than in it for the same reason `SETTINGS_TABS` is: a
 * route file may export nothing but the route, and this table has to be
 * readable by what else needs it - the command palette, which offers these
 * pages as jump targets and would otherwise restate them.
 */
export const ADMIN_TABS: readonly PageTab[] = [
  { labelKey: "overview", href: ROUTES.ADMIN, icon: LayoutDashboard, exact: true },
  { labelKey: "users", href: ROUTES.ADMIN_USERS, icon: Users },
  // Not `organizations`: the sidebar already offers the caller's own orgs page
  // under that name, and the palette lists both - two identical options with
  // different destinations. This one is the deployment's whole tenant list.
  { labelKey: "allOrganizations", href: ROUTES.ADMIN_ORGANIZATIONS, icon: Building2 },
  { labelKey: "conversations", href: ROUTES.ADMIN_CONVERSATIONS, icon: MessageSquare },
  { labelKey: "system", href: ROUTES.ADMIN_SYSTEM, icon: Activity },
  // Last, and named for the deployment rather than for the app: `settings` alone
  // is what the sidebar already calls a person's own preferences, and the palette
  // lists both.
  { labelKey: "deploymentSettings", href: ROUTES.ADMIN_SETTINGS, icon: Settings },
];
