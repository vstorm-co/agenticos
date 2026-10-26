import { useTranslations } from "next-intl";

import { Skeleton } from "@/components/ui/skeleton";
import {
  ARRANGED_GRID_CLASS,
  ROW_CLASS,
  SPAN_CLASS,
  type SectionDef,
} from "@/lib/dashboard/layouts";
import { WIDGETS } from "@/lib/dashboard/registry";
import { BAND_GAP, HEADING_GAP } from "@/lib/dashboard/system";
import { cn } from "@/lib/utils";
import { WidgetFrame } from "./widget-frame";
import { WidgetSkeleton } from "./widget-states";

/** The saved/default placements also own the loading grid's widths and heights. */
export function DashboardSkeleton({ sections }: { sections: SectionDef[] }) {
  const t = useTranslations("dashboard");
  return (
    <div role="status" aria-label={t("states.loading")}>
      <Skeleton className="h-10 w-full" aria-hidden />
      <div className={cn(BAND_GAP, "mt-6")} aria-hidden>
        {sections.map((section) => (
          <section key={section.id}>
            {!!(section.title || section.titleKey) && <Skeleton className="h-5 w-40" />}
            {!section.collapsed && (
              <div
                className={cn(
                  ARRANGED_GRID_CLASS,
                  !!(section.title || section.titleKey) && HEADING_GAP,
                )}
              >
                {section.entries.map((entry, index) => (
                  <div
                    key={`${entry.widget}-${index}`}
                    className={cn(
                      SPAN_CLASS[entry.span],
                      ROW_CLASS[entry.rows ?? WIDGETS[entry.widget].defaultRows],
                    )}
                  >
                    <WidgetFrame title={t(entry.titleKey ?? `widgets.${entry.widget}.title`)}>
                      <WidgetSkeleton />
                    </WidgetFrame>
                  </div>
                ))}
              </div>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
