import { Activity, LayoutDashboard, MessageSquare, Star, Users } from "lucide-react";

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
  { labelKey: "conversations", href: ROUTES.ADMIN_CONVERSATIONS, icon: MessageSquare },
  { labelKey: "ratings", href: ROUTES.ADMIN_RATINGS, icon: Star },
  { labelKey: "system", href: ROUTES.ADMIN_SYSTEM, icon: Activity },
];
