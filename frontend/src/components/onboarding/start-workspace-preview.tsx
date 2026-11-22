"use client";

import type { Organization } from "@/types";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { Building2, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { useStartVariant } from "./start-experience";
import { StartCompanions } from "./start-companions";
import styles from "./administration.module.css";

/** A live illustration of the workspace being named, before anything is created. */
export function StartWorkspacePreview({
  name,
  organization,
}: {
  name: string;
  organization?: Organization;
}) {
  const variant = useStartVariant();
  const t = useTranslations("start.administration");
  if (variant === "studio") return null;
  return (
    <aside className={styles.workspacePreview} aria-label={t("preview")}>
      <p className={styles.previewLabel}>{t("preview")}</p>
      <h3>{t("previewTitle")}</h3>
      <div className={styles.workspaceMap}>
        <svg
          className={styles.mapConnections}
          viewBox="0 0 100 160"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <path d="M50 75V90Q50 105 40 105H15V135M50 90Q50 105 60 105H85V135" />
        </svg>
        <div className={styles.previewOrganization}>
          <span
            className={organization ? styles.workspaceLogo : styles.workspaceMonogram}
            aria-hidden="true"
          >
            {organization ? (
              <EntityAvatar
                seed={organization.id}
                name={organization.name}
                imageSrc={`/api/orgs/${organization.id}/avatar?v=${organization.updated_at ?? ""}`}
                hasImage={!!organization.avatar_url}
                colorSlot={organization.avatar_color}
                size="lg"
                ariaHidden
              />
            ) : name.trim() ? (
              Array.from(name.trim())[0]?.toLocaleUpperCase()
            ) : (
              <Building2 size={25} />
            )}
          </span>
          <strong>{name.trim() || t("previewName")}</strong>
        </div>
        <div className={styles.previewTeam}>
          <span className={styles.previewPeople} aria-hidden="true">
            <Users size={27} />
          </span>
          <span>{t("previewTeam")}</span>
        </div>
        <div className={styles.previewAgents}>
          <span className={styles.previewFace} aria-hidden="true">
            <StartCompanions members={["nimbus", "byte", "sunny"]} />
          </span>
          <span>{t("previewAgents")}</span>
        </div>
      </div>
      <p className={styles.previewHint}>{t("previewHint")}</p>
    </aside>
  );
}
