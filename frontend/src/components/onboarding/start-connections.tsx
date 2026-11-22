"use client";

import { useTranslations } from "next-intl";
import { ChatModelPicker } from "@/components/chat/chat-model-picker";
import { McpServerList } from "@/components/mcp/mcp-server-list";
import { useSavedChatControls } from "@/hooks/use-saved-chat-controls";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import styles from "./start-experience.module.css";

/** The normal chat picker keeps personal accounts separate from shared agent defaults. */
export function StartModels() {
  const t = useTranslations("start.experience");
  const controls = useSavedChatControls();
  return (
    <div className={styles.connectionStage}>
      <p className={styles.connectionHint}>{t("modelsHint")}</p>
      <ChatModelPicker
        presentation="library"
        defaultProviderId="openrouter"
        value={controls.modelProfileId}
        agentModel={null}
        onChange={(modelProfileId) => controls.update({ modelProfileId })}
      />
      <p className={styles.connectionFootnote}>{t("modelsScope")}</p>
    </div>
  );
}

/** Existing connection dialogs own OAuth, Vault storage and personal/shared scope. */
export function StartTools() {
  const t = useTranslations("start.experience");
  const { can } = usePermissions();
  return (
    <div className={styles.connectionStage}>
      <p className={styles.connectionHint}>{t("toolsHint")}</p>
      <div className={styles.catalogViewport} data-start-catalog>
        <McpServerList canManageOrganization={can(Perm.mcpManage)} persistSelection={false} />
      </div>
      <p className={styles.connectionFootnote}>{t("toolsScope")}</p>
    </div>
  );
}
