import type { Period } from "@/lib/dashboard/period";

/**
 * The one signature every widget renders with, so the page can map a layout
 * generically. Widgets that deliberately ignore the period filter (the
 * month-to-date figures, health lists, personal lists) simply don't read it.
 */
export interface DashboardWidgetProps {
  title: string;
  /**
   * One sentence saying what the card answers, shown behind the info icon in
   * its header. The page supplies the widget's own `description` message - the
   * same sentence the add-widget catalog lists it under, so the card a person
   * chose reads back the way it was offered.
   */
  hint: string;
  period: Period;
  seeAll?: string;
}
