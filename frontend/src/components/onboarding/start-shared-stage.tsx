"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { OrganizationProfileSettings } from "@/components/teams/organization-profile-settings";
import type { Organization } from "@/types";
import type { OrganizationStartStep } from "@/lib/onboarding/scopes";
import { StartActions, StartNavigationScope } from "./start-navigation";
import { StartWorkspace } from "./start-workspace";
import { StartDeployment } from "./start-deployment";
import { StartOrganizationResources } from "./start-organization-resources";
import { StartInviteTeam } from "./start-invite-team";
import { StartOrganizationSettings } from "./start-organization-settings";

export type SharedStartStep = OrganizationStartStep | "deployment";
export function StartSharedStage({
  step,
  active,
  org,
  organizations,
  onSelect,
  onNext,
  onBack,
}: {
  step: SharedStartStep;
  active: boolean;
  org?: Organization;
  organizations: Organization[];
  onSelect: (id: string) => void;
  onNext: () => void;
  onBack?: () => void;
}) {
  const t = useTranslations("start.administration");
  const experience = useTranslations("start.experience");
  if (step === "deployment")
    return <StartDeployment org={org} active={active} onContinue={onNext} onBack={onBack} />;
  if (step === "workspace")
    return (
      <StartWorkspace
        organizations={organizations}
        activeOrgId={org?.id ?? null}
        onSelect={onSelect}
      />
    );
  if (!org) return null;
  if (step === "identity")
    return (
      <OrganizationProfileSettings
        org={org}
        onContinue={onNext}
        saveLabel={t("saveContinue")}
        renderActions={(actions) => <StartActions>{actions}</StartActions>}
      />
    );
  if (step === "team") return <StartInviteTeam org={org} onContinue={onNext} />;
  if (step === "organization")
    return (
      <StartOrganizationSettings org={org} active={active} onBack={onBack} onContinue={onNext} />
    );
  return (
    <>
      <StartOrganizationResources kind={step} />
      <StartNavigationScope active={active}>
        <StartActions>
          <Button onClick={onNext}>{experience("continue")}</Button>
        </StartActions>
      </StartNavigationScope>
    </>
  );
}
