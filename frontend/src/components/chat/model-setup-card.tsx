"use client";

import Link from "next/link";
import { ArrowUpRight, KeyRound, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { StartCompanions } from "@/components/onboarding/start-companions";
import { usePermissions } from "@/hooks/use-permissions";
import { useStart } from "@/hooks/use-start";
import { Perm } from "@/types/permissions";
import styles from "./model-setup-card.module.css";

/** A setup receipt, not a generated answer or a successful AI run. */
export function ModelSetupCard({
  agentId,
  interactive = false,
  canConfigure,
}: {
  agentId?: string;
  interactive?: boolean;
  canConfigure?: boolean;
}) {
  const t = useTranslations("chat.modelSetup");
  return (
    <div className={styles.reply}>
      <section className={styles.card} aria-label={t("title")}>
        <div className={styles.artwork} aria-hidden="true">
          <span className={styles.key}>
            <KeyRound size={26} strokeWidth={1.5} />
          </span>
          <StartCompanions members={["pebble", "mochi", "byte"]} />
        </div>
        <div className={styles.body}>
          <p className={styles.label}>{t("eyebrow")}</p>
          <h3>{t("title")}</h3>
          <p>{t("description")}</p>
          <ol className={styles.steps}>
            <li>
              <span>1</span>
              {t("provider")}
            </li>
            <li>
              <span>2</span>
              {t("key")}
            </li>
            <li>
              <span>3</span>
              {t("publish")}
            </li>
          </ol>
          {interactive && agentId && <SetupActions agentId={agentId} canConfigure={canConfigure} />}
          <p className={styles.notice}>
            <ShieldCheck size={14} aria-hidden />
            {t("notice")}
          </p>
        </div>
      </section>
    </div>
  );
}
function SetupActions({ agentId, canConfigure }: { agentId: string; canConfigure?: boolean }) {
  const t = useTranslations("chat.modelSetup");
  const { can, isLoaded } = usePermissions();
  const start = useStart();
  if (!isLoaded) return null;
  if (canConfigure !== false && can(Perm.connectionsManage) && can(Perm.agentsEdit))
    return (
      <Link className={styles.action} href={`/agents/${agentId}?highlight=agent-model-picker`}>
        {t("action")}
        <ArrowUpRight size={16} aria-hidden />
      </Link>
    );
  const email = start.data?.support_email;
  return (
    <div className={styles.owner}>
      <p>{t("ownerHint")}</p>
      {email && (
        <a href={`mailto:${email}`} className={styles.ownerLink}>
          {t("contact")}
          <ArrowUpRight size={14} aria-hidden />
        </a>
      )}
    </div>
  );
}
