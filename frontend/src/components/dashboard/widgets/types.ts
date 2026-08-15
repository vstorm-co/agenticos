import type { WidgetOptions } from "@/lib/dashboard/layouts";
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
  /**
   * The window this card draws. Already resolved by the page: a card pinning
   * its own preset gets that one, everything else gets the page's filter, so a
   * widget never has to know which of the two it is looking at.
   */
  period: Period;
  seeAll?: string;
  /**
   * What this placement overrides about itself - which style to draw in, and
   * which agent or person to narrow to. Sanitized against the widget's own
   * declaration before it arrives, so a widget may honour whatever it finds
   * here without checking that it offered it.
   */
  options?: WidgetOptions;
}
