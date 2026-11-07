"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useStart } from "@/hooks/use-start";
import { Button } from "@/components/ui";
import { cn } from "@/lib/utils";

/** The dashboard links to the same start as invitations and native apps. */
export function StartChecklist({ orgId, className }: { orgId: string; className?: string }) {
  const state = useStart();
  const t = useTranslations("start");
  if (
    !state.data ||
    state.error ||
    state.data.organization_id !== orgId ||
    state.data.dismissed ||
    state.data.has_result
  )
    return null;
  return (
    <section className={cn("mt-6 space-y-3 rounded-xl border p-5", className)}>
      <h2 className="font-semibold">{t("offerTitle")}</h2>
      <p className="text-muted-foreground text-sm">{t("offerHint")}</p>
      <div className="flex items-center gap-2">
        <Link href="/onboarding" className="rounded-lg border px-3 py-2 text-sm">
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
      {state.save.isError && <p role="alert">{t("loadFailed")}</p>}
    </section>
  );
}
