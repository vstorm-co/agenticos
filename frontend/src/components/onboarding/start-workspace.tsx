"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Building2, ArrowRight } from "lucide-react";
import { Button, Label } from "@/components/ui";
import { CreateOrgForm } from "@/components/teams/create-org-form";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import type { Organization } from "@/types";
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
  const t = useTranslations("start.administration");
  const [name, setName] = useState("");
  const companies = organizations.filter((org) => !org.is_personal);
  const [createNew, setCreateNew] = useState(companies.length === 0);
  return (
    <div className={styles.workspaceChoice}>
      {createNew && (
        <div className={styles.workspaceStudio}>
          <section className={styles.createWorkspace}>
            <Building2 size={24} aria-hidden className={styles.stageIcon} />
            <h3>{t("createCompany")}</h3>
            <p>{t("createCompanyHint")}</p>
            <CreateOrgForm onCreated={onSelect} onNameChange={setName} />
          </section>
          <StartWorkspacePreview name={name} />
        </div>
      )}
      {!createNew && companies.length > 0 && (
        <div className={styles.workspaceStudio}>
          <section className={styles.createWorkspace}>
            <Building2 size={24} aria-hidden className={styles.stageIcon} />
            <h3>{t("existingCompany")}</h3>
            <p>{t("existingCompanyHint")}</p>
            <ul className={styles.workspaceList}>
              {companies.map((org) => (
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
            <Button variant="ghost" onClick={() => setCreateNew(true)}>
              {t("createInstead")}
            </Button>
          </section>
          <StartWorkspacePreview
            organization={companies.find((org) => org.id === activeOrgId) ?? companies[0]}
            name={companies.find((org) => org.id === activeOrgId)?.name ?? companies[0]?.name ?? ""}
          />
        </div>
      )}
      {createNew && companies.length > 0 && (
        <Button variant="ghost" onClick={() => setCreateNew(false)}>
          {t("chooseExisting")}
        </Button>
      )}
      {organizations.some((org) => org.is_personal) && (
        <details className={styles.personalChoice}>
          <summary>{t("usePersonal")}</summary>
          <p className={styles.explanation}>{t("personalExplanation")}</p>
          <Label htmlFor="setup-personal">{t("personalChoice")}</Label>
          <select
            id="setup-personal"
            value={activeOrgId ?? ""}
            onChange={(event) => onSelect(event.target.value)}
          >
            <option value="" disabled>
              {t("selectWorkspace")}
            </option>
            {organizations
              .filter((org) => org.is_personal)
              .map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
          </select>
          {organizations.some((org) => org.id === activeOrgId && org.is_personal) && (
            <Button
              variant="outline"
              onClick={() => {
                if (activeOrgId) onSelect(activeOrgId);
              }}
            >
              {t("continuePersonal")}
            </Button>
          )}
        </details>
      )}
    </div>
  );
}
