import type { Period } from "@/lib/dashboard/period";

/**
 * The one signature every widget renders with, so the page can map a layout
 * generically. Widgets that deliberately ignore the period filter (the
 * month-to-date figures, health lists, personal lists) simply don't read it.
 */
export interface DashboardWidgetProps {
  title: string;
  period: Period;
  seeAll?: string;
}
