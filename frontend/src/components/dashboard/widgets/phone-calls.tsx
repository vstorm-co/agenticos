"use client";
import { Phone } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePhoneCalls } from "@/hooks/use-phone";
import { PhoneReceiptCard } from "@/components/phone/phone-call-card";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

export function PhoneCallsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.phone-calls");
  const query = usePhoneCalls();
  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {query.isLoading ? (
        <WidgetSkeleton />
      ) : query.error ? (
        <WidgetErrorBody onRetry={query.refetch} />
      ) : !query.data?.length ? (
        <WidgetEmptyBody
          icon={Phone}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <div className="space-y-2">
          {query.data.slice(0, 3).map((call) => (
            <PhoneReceiptCard key={call.id} call={call} />
          ))}
        </div>
      )}
    </WidgetFrame>
  );
}
