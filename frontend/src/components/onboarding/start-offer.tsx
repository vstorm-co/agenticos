"use client";

import Link from "next/link";
import { ArrowRight, LoaderCircle, X } from "lucide-react";
import { usePathname, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { AvatarFace } from "@/components/ui/avatar-face";
import { shouldOfferStart } from "@/lib/onboarding-api";
import { useStart } from "@/hooks/use-start";
import { useOrganizations } from "@/hooks/use-organizations";
import { useBranding } from "@/components/branding/branding-provider";
import { useBrandingNotice } from "@/hooks/use-branding-notice";
import { usePermissions } from "@/hooks/use-permissions";
import { useAuthStore } from "@/stores/auth-store";
import { Perm } from "@/types/permissions";
import { stripLocale } from "@/lib/active-route";
import styles from "./start-offer.module.css";
import noticeStyles from "@/components/layout/account-notices.module.css";

/** A quiet way into the shared start; never interrupts an invitation or an existing chat. */
export function StartOffer() {
  const path = stripLocale(usePathname());
  const params = useSearchParams();
  const state = useStart();
  const { activeOrg } = useOrganizations();
  const permissions = usePermissions();
  const user = useAuthStore((s) => s.user);
  const appAdmin = user?.is_app_admin === true;
  const { maintenanceMode } = useBranding();
  const { data: notice } = useBrandingNotice(!!user);
  const administrator =
    appAdmin || (!!activeOrg && !activeOrg.is_personal && permissions.can(Perm.orgSettings));
  const t = useTranslations("start.offer");
  const tStart = useTranslations("start");
  if (
    ((notice?.maintenance_mode ?? maintenanceMode) && !appAdmin) ||
    params.has("id") ||
    params.has("example") ||
    !state.data ||
    state.error ||
    !shouldOfferStart(state.data) ||
    path !== "/chat"
  )
    return null;
  return (
    <aside
      className={`${styles.notice} ${noticeStyles.surface}`}
      aria-label={t(administrator ? "adminTitle" : "memberTitle")}
    >
      <span className={styles.companion} aria-hidden="true">
        <AvatarFace seed="agenticos" background={false} />
      </span>
      <div className={styles.copy}>
        <p className={styles.workspace}>{state.data.organization_name}</p>
        <p className={styles.title}>{t(administrator ? "adminTitle" : "memberTitle")}</p>
        <p className={styles.hint}>{t(administrator ? "adminHint" : "memberHint")}</p>
      </div>
      <Link className={styles.action} href="/onboarding">
        {t(administrator ? "adminAction" : "memberAction")}
        <ArrowRight size={15} aria-hidden />
      </Link>
      <Button
        className={styles.dismiss}
        variant="ghost"
        size="icon"
        aria-label={t("dismiss")}
        title={t("dismiss")}
        disabled={state.save.isPending}
        aria-busy={state.save.isPending}
        onClick={() => state.save.mutate({ dismissed: true })}
      >
        {state.save.isPending ? (
          <LoaderCircle size={15} className="animate-spin motion-reduce:animate-none" aria-hidden />
        ) : (
          <X size={16} aria-hidden />
        )}
      </Button>
      {state.save.isError && (
        <p role="alert" className={styles.error}>
          {tStart("loadFailed")}
        </p>
      )}
    </aside>
  );
}
