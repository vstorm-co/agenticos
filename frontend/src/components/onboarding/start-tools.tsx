"use client";

import { useTranslations } from "next-intl";

import { McpServerList } from "@/components/mcp/mcp-server-list";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import styles from "./start-experience.module.css";

/** A few useful services first; existing dialogs own accounts, OAuth and scope. */
export function StartTools() {
  const t = useTranslations("start.experience");
  const { can } = usePermissions();
  return (
    <div className={styles.connectionStage}>
      <p className={styles.connectionHint}>{t("toolsHint")}</p>
      <div className={styles.catalogViewport} data-start-catalog>
        <McpServerList
          presentation="onboarding"
          canManageOrganization={can(Perm.mcpManage)}
          persistSelection={false}
        />
      </div>
      <p className={styles.connectionFootnote}>{t("toolsScope")}</p>
    </div>
  );
}
