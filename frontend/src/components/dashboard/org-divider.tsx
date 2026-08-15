"use client";

import { useTranslations } from "next-intl";

/**
 * The app admin's boundary line: the deployment strip above, one
 * organization below. Which organization is the existing switcher's job -
 * this only says whose numbers follow, so cross-tenant reading stays a
 * deliberate act rather than a scroll.
 */
export function OrgDivider({ name }: { name: string | null }) {
  const t = useTranslations("dashboard.orgDivider");
  return (
    <div className="border-border flex items-baseline gap-2 border-t pt-4">
      <span className="text-muted-foreground font-mono text-[11px] font-medium tracking-[0.1em] uppercase">
        {t("label")}
      </span>
      {name ? (
        <span className="text-foreground text-sm font-semibold tracking-tight">{name}</span>
      ) : null}
      <span className="text-muted-foreground text-xs">— {t("note")}</span>
    </div>
  );
}
