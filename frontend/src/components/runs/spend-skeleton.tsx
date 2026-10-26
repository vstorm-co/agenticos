import { useTranslations } from "next-intl";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  FigureCard,
} from "@/components/ui";
import { Skeleton } from "@/components/ui/skeleton";
import { LoadingState } from "@/components/states";

export function SpendSkeleton() {
  const t = useTranslations("pages.runs");
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(["spendWindow", "monthToDate", "perRun", "dearestAgent"] as const).map((label) => (
          <FigureCard
            key={label}
            label={t(label)}
            value={
              <span
                aria-hidden
                className="bg-muted inline-block h-8 w-24 animate-pulse rounded-md"
              />
            }
            caption={
              <span
                aria-hidden
                className="bg-muted inline-block h-4 w-32 animate-pulse rounded-md"
              />
            }
          />
        ))}
      </div>
      <Card>
        <CardHeader className="space-y-1 px-5 pt-4 pb-2">
          <CardTitle className="text-sm">{t("spendOverTime")}</CardTitle>
          <CardDescription className="text-xs">{t("spendOverTimeHint")}</CardDescription>
        </CardHeader>
        <CardContent className="px-3 pb-4">
          <Skeleton className="h-40 w-full" />
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="border-b px-5 py-4">
          <CardTitle className="text-sm">{t("whereTheMoneyWent")}</CardTitle>
          <Skeleton className="h-4 w-32" />
        </CardHeader>
        <CardContent className="p-0">
          <div className="border-b px-5 py-3">
            <Skeleton className="h-8 w-64 max-w-full" />
          </div>
          <LoadingState variant="skeleton-table" columns={4} rows={6} className="px-5" />
        </CardContent>
      </Card>
    </div>
  );
}
