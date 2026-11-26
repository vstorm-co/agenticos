"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ArrowRight, Building2, Plus } from "lucide-react";
import { Button } from "@/components/ui";
import { CreateOrgForm } from "@/components/teams/create-org-form";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import type { Organization } from "@/types";
import { StartActions, StartBack } from "./start-navigation";
import { useStartVariant } from "./start-experience";
import { StartWorkspacePreview } from "./start-workspace-preview";
import styles from "./administration.module.css";

export function StartWorkspace({
  organizations,
  activeOrgId,
  onSelect,
}: {
  organizations: Organization[];
  activeOrgId: string | null;
  onSelect: (id: string) => void;
}) {
  const variant = useStartVariant();
  const t = useTranslations("start.administration");
  const [name, setName] = useState("");
  const [createNew, setCreateNew] = useState(organizations.length === 0);
  const organization = organizations.find((org) => org.id === activeOrgId) ?? organizations[0];

  return (
    <div className={styles.workspaceStudio} data-start-workspace>
      {createNew ? (
        <section className={styles.createWorkspace} data-start-workspace-form>
          <Building2 size={24} aria-hidden className={styles.stageIcon} />
          <h3>{t("createCompany")}</h3>
          <p>{t("createCompanyHint")}</p>
          <CreateOrgForm
            onCreated={onSelect}
            onNameChange={setName}
            renderActions={(actions) => (
              <StartActions
                back={
                  organizations.length > 0 && (
                    <StartBack
                      onClick={() => {
                        setName("");
                        setCreateNew(false);
                      }}
                    />
                  )
                }
              >
                {actions}
              </StartActions>
            )}
          />
        </section>
      ) : (
        <section className={styles.createWorkspace} data-start-workspace-form>
          {variant !== "studio" && (
            <>
              <Building2 size={24} aria-hidden className={styles.stageIcon} />
              <h3>{t("existingCompany")}</h3>
              <p>{t("existingCompanyHint")}</p>
            </>
          )}
          <ul className={styles.workspaceList}>
            {organizations.map((org) => (
              <li key={org.id}>
                <Button variant="outline" onClick={() => onSelect(org.id)}>
                  <EntityAvatar
                    seed={org.id}
                    name={org.name}
                    imageSrc={`/api/orgs/${org.id}/avatar?v=${org.updated_at ?? ""}`}
                    hasImage={!!org.avatar_url}
                    colorSlot={org.avatar_color}
                    ariaHidden
                  />
                  {org.name}
                  <ArrowRight size={16} aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
          <Button
            className={styles.newWorkspace}
            variant="outline"
            onClick={() => setCreateNew(true)}
          >
            <Plus size={16} aria-hidden />
            {t("createInstead")}
          </Button>
        </section>
      )}
      <StartWorkspacePreview
        organization={createNew ? undefined : organization}
        name={createNew ? name : (organization?.name ?? "")}
      />
    </div>
  );
}
