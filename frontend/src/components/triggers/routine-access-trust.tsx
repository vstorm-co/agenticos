"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { useTranslations } from "next-intl";

import { ConfirmDialog, Switch } from "@/components/ui";
import type { RoutineAccessMode, RoutineAccessReview } from "@/lib/routine-access-api";
import { useOrgStore } from "@/stores";

/**
 * Trust the agent: follow its future sources and tools without a new review.
 *
 * Always shown, so the option can be found: where the creator may not choose
 * it, it stays off and says why, with the way to the organization setting
 * when that is what stands in the way. Off is always possible; on asks first.
 */
export function RoutineAccessTrust({
  review,
  mode,
  disabled,
  onChange,
}: {
  review: RoutineAccessReview;
  mode: RoutineAccessMode;
  disabled: boolean;
  onChange: (mode: RoutineAccessMode) => void;
}) {
  const t = useTranslations("triggers.access");
  const id = useId();
  const [confirming, setConfirming] = useState(false);
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const on = mode === "trust_agent";
  return (
    <section
      aria-labelledby={`${id}-heading`}
      className="border-destructive/40 space-y-2 rounded-lg border p-3"
    >
      <h3 id={`${id}-heading`} className="text-destructive-ink text-sm font-semibold">
        {t("dangerZone")}
      </h3>
      <div className="flex items-start gap-3">
        <Switch
          id={`${id}-switch`}
          aria-describedby={`${id}-warning`}
          checked={on}
          // Off is always possible; on only where the server would accept it.
          disabled={disabled || (!on && !review.can_trust)}
          onCheckedChange={(next) => (next ? setConfirming(true) : onChange("reviewed"))}
        />
        <div className="space-y-1">
          <label htmlFor={`${id}-switch`} className="text-sm font-medium">
            {t("trust")}
          </label>
          <p id={`${id}-warning`} className="text-muted-foreground text-xs">
            {t("trustWarning")}
          </p>
          {!review.can_trust && (
            <p className="text-xs">
              {t("trustRefused", { reason: review.trust_blocked_reason ?? "other" })}{" "}
              {review.trust_blocked_reason === "organization" && activeOrgId && (
                <Link
                  href={`/orgs/${activeOrgId}/members?tab=governance`}
                  className="underline underline-offset-4"
                >
                  {t("trustSetting")}
                </Link>
              )}
            </p>
          )}
        </div>
      </div>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("trustConfirmTitle")}
        description={t("trustConfirmDescription")}
        confirmLabel={t("trust")}
        destructive
        onConfirm={() => {
          onChange("trust_agent");
          setConfirming(false);
        }}
      />
    </section>
  );
}
