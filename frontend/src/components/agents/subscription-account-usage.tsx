"use client";

import { useTranslations } from "next-intl";
import { RefreshCw } from "lucide-react";
import { Button, Spinner } from "@/components/ui";
import { useSubscriptionUsage } from "@/hooks/use-subscription-accounts";
import type { SubscriptionAccount } from "@/lib/subscription-accounts-api";
import { SubscriptionUsage } from "./subscription-usage";

/** Both account settings and the model picker show the same per-account limits. */
export function SubscriptionAccountUsage({
  account,
  compact = false,
}: {
  account: SubscriptionAccount;
  compact?: boolean;
}) {
  const t = useTranslations("modelSources");
  const query = useSubscriptionUsage(
    account.name,
    !account.disabled && !account.unavailable,
    account.provider,
  );
  const usage = query.data ?? account.usage;
  const reported = usage && usage.status !== "unavailable" && usage.windows.length > 0;
  return (
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1 space-y-1">
        {reported ? (
          <SubscriptionUsage usage={usage} compact={compact} />
        ) : (
          <p className="text-muted-foreground text-xs">{t("usageAndLimits")}</p>
        )}
        {query.error ? (
          <p role="alert" className="text-destructive text-xs">
            {t("usageFailed")}
          </p>
        ) : !query.isLoading && !reported ? (
          <p className="text-muted-foreground text-xs">{t("usageUnavailable")}</p>
        ) : null}
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label={t("refreshUsage")}
        disabled={query.isFetching || account.disabled || account.unavailable}
        onClick={() => void query.refetch()}
      >
        {query.isFetching ? (
          <Spinner className="size-3" />
        ) : (
          <RefreshCw className="size-3" aria-hidden />
        )}
      </Button>
    </div>
  );
}
