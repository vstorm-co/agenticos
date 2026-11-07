"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useStart } from "@/hooks/use-start";
import { stripLocale } from "@/lib/active-route";

/** A quiet way into the shared start; never interrupts an invitation or an existing chat. */
export function StartOffer() {
  const path = stripLocale(usePathname());
  const params = useSearchParams();
  const state = useStart();
  const t = useTranslations("start");
  if (
    params.has("id") ||
    params.has("example") ||
    !state.data ||
    state.error ||
    state.data.dismissed ||
    state.data.has_result ||
    path !== "/chat"
  )
    return null;
  return (
    <aside
      className="border-border flex flex-wrap items-center justify-between gap-3 border-b px-5 py-3"
      aria-label={t("offerTitle")}
    >
      <div>
        <p className="text-sm font-medium">
          {state.data.organization_name} · {t("offerTitle")}
        </p>
        <p className="text-muted-foreground text-xs">{t("offerHint")}</p>
      </div>
      <div className="flex items-center gap-2">
        <Link className="rounded-lg border px-3 py-2 text-sm" href="/onboarding">
          {t("openStart")}
        </Link>
        <Button
          variant="ghost"
          size="sm"
          disabled={state.save.isPending}
          onClick={() => state.save.mutate({ dismissed: true })}
        >
          {t("later")}
        </Button>
      </div>
      {state.save.isError && (
        <p role="alert" className="text-destructive text-xs">
          {t("loadFailed")}
        </p>
      )}
    </aside>
  );
}
