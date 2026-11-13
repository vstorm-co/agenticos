"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { shouldOfferStart } from "@/lib/onboarding-api";
import { useStart } from "@/hooks/use-start";
import { Button } from "@/components/ui";
import { LoadingState } from "@/components/states";
import { StartCompanions } from "@/components/onboarding/start-companions";
import styles from "./start-checklist.module.css";
import { ArrowRight, NotebookPen, RotateCw } from "lucide-react";
import { cn } from "@/lib/utils";

/** The dashboard links to the same start as invitations and native apps. */
export function StartChecklist({ orgId, className }: { orgId: string; className?: string }) {
  const state = useStart();
  const t = useTranslations("start");
  const frame = cn(
    "mt-6 flex min-h-[22rem] flex-col justify-center gap-4 rounded-xl border bg-card p-6 lg:h-[31rem]",
    className,
  );
  if (state.isLoading || state.waitingForScope)
    return (
      <section aria-label={t("offerTitle")} className={frame}>
        <h2 className="font-semibold">{t("offerTitle")}</h2>
        <LoadingState variant="pending" />
      </section>
    );
  if (state.error)
    return (
      <section aria-label={t("offerTitle")} className={frame}>
        <h2 className="font-semibold">{t("offerTitle")}</h2>
        <p role="alert" className="text-muted-foreground text-sm">
          {t("loadFailed")}
        </p>
        <Button variant="outline" onClick={() => void state.refetch()}>
          <RotateCw size={14} aria-hidden />
          {t("retry")}
        </Button>
      </section>
    );
  if (!state.data || state.data.organization_id !== orgId || !shouldOfferStart(state.data))
    return null;
  return (
    <section aria-label={t("offerTitle")} className={cn(frame, "h-auto")}>
      <div className={styles.artwork} aria-hidden="true">
        <span className={styles.orbit} />
        <span className={styles.task}>
          <NotebookPen size={30} strokeWidth={1.5} />
        </span>
        <StartCompanions members={["pebble", "mochi", "byte"]} />
      </div>
      <h2 className="font-semibold">{t("offerTitle")}</h2>
      <p className="text-muted-foreground text-sm">{t("offerHint")}</p>
      <div className="flex flex-wrap items-center gap-2">
        <Link
          href="/onboarding"
          className="bg-primary text-primary-foreground inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm"
        >
          {t("openStart")}
          <ArrowRight size={14} aria-hidden />
        </Link>
        <Button
          variant="ghost"
          size="sm"
          disabled={state.save.isPending}
          onClick={() => state.save.mutate({ dismissed: true })}
        >
          {t("snooze")}
        </Button>
      </div>
      {state.save.isError && <p role="alert">{t("loadFailed")}</p>}
    </section>
  );
}
