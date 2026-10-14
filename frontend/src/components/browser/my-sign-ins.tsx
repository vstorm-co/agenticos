"use client";

import { Globe, KeyRound } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, Card } from "@/components/ui";
import { useBrowserSignIns } from "@/hooks/use-browser-sign-ins";

/**
 * The sites your agents' browser starts signed in to, and forgetting one (#2129).
 *
 * A sign-in arrives here only one way: you took the browser over during a
 * browse acting as you, signed in, and handed it back with "Keep me signed in"
 * ticked. Forgetting it means the next browse starts signed out there. What a
 * sign-in holds - cookies, storage - is never shown, and no route returns it.
 */
export function MySignIns() {
  const t = useTranslations("pages.signIns");
  const format = useFormatter();
  const { signIns, isLoading, error, forget } = useBrowserSignIns();

  if (isLoading) return <LoadingState variant="skeleton-list" rows={2} />;
  if (error) return <ErrorState />;
  if (signIns.length === 0) {
    return <EmptyState icon={KeyRound} title={t("empty")} description={t("emptyHint")} />;
  }

  const date = (stamp: string | null) =>
    stamp ? format.dateTime(new Date(stamp), { dateStyle: "medium" }) : null;

  return (
    <Card className="divide-border divide-y" data-tour="my-sign-ins">
      {signIns.map((signIn) => {
        const used = date(signIn.last_used_at);
        return (
          <div key={signIn.id} className="flex items-center gap-3 px-5 py-3">
            <span className="bg-muted flex size-9 shrink-0 items-center justify-center rounded-lg">
              <Globe className="text-muted-foreground size-4" aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{signIn.site}</p>
              <p className="text-muted-foreground text-xs">
                {used
                  ? t("savedAndUsed", { saved: date(signIn.created_at) ?? "", used })
                  : t("saved", { saved: date(signIn.created_at) ?? "" })}
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={() => void forget(signIn.id)}>
              {t("forget")}
            </Button>
          </div>
        );
      })}
    </Card>
  );
}
