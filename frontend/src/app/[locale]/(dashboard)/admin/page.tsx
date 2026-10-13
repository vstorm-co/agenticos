import { redirect } from "next/navigation";

import { ROUTES } from "@/lib/constants";

/**
 * The section index, which redirects rather than rendering - the same shape
 * `/settings/` takes.
 *
 * It used to be an Overview: six figures from `/admin/stats` and three links to
 * the tabs directly above them. Both halves were already on screen elsewhere.
 * The figures are the `platform` widget, reading the same endpoint through
 * `useAdminStats`, on a dashboard the reader can arrange (#213); the links were
 * three of the five tabs in this section's own strip, so a third of the page was
 * navigation to where the reader already was. Two copies of six numbers disagree
 * the first time one of them is edited, and the arrangeable dashboard is the
 * answer to "where do the deployment's figures live" (#922).
 */
export default function AdminIndex() {
  redirect(ROUTES.ADMIN_USERS);
}
