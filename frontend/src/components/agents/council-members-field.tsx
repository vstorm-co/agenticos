"use client";

import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { Input, Label } from "@/components/ui";
import { useModelProviders } from "@/hooks";
import { useTranslations } from "next-intl";

interface CouncilMember {
  name: string;
  provider: string;
  model_profile_id: string;
}

interface CouncilMembersFieldProps {
  idPrefix: string;
  value: unknown;
  onChange: (members: CouncilMember[]) => void;
  disabled?: boolean;
}

const MEMBER_COUNT = 3;

function readMember(value: unknown): CouncilMember {
  if (typeof value !== "object" || value === null) {
    return { name: "", provider: "", model_profile_id: "" };
  }
  const member = value as Record<string, unknown>;
  return {
    name: typeof member.name === "string" ? member.name : "",
    provider: typeof member.provider === "string" ? member.provider : "",
    model_profile_id: typeof member.model_profile_id === "string" ? member.model_profile_id : "",
  };
}

export function CouncilMembersField({
  idPrefix,
  value,
  onChange,
  disabled,
}: CouncilMembersFieldProps) {
  const t = useTranslations("agents");
  const { profiles, profilesStatus } = useModelProviders();
  const entries: unknown[] = Array.isArray(value) ? value : [];
  const members = Array.from({ length: MEMBER_COUNT }, (_, index) => readMember(entries[index]));

  const edit = (index: number, changes: Partial<CouncilMember>) => {
    const next = members.map((member, memberIndex) =>
      memberIndex === index ? { ...member, ...changes } : member,
    );
    onChange(next);
  };

  return (
    <div className="space-y-3">
      <p className="text-muted-foreground text-xs">{t("councilMembersProviderHint")}</p>
      {members.map((member, index) => {
        const rowId = `${idPrefix}-council-member-${index + 1}`;
        return (
          <fieldset key={rowId} disabled={disabled} className="space-y-3 rounded-md border p-3">
            <legend className="px-1 text-sm font-medium">
              {t("councilMemberRow", { number: index + 1 })}
            </legend>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor={`${rowId}-name`}>{t("councilMemberName")}</Label>
                <Input
                  id={`${rowId}-name`}
                  value={member.name}
                  minLength={1}
                  maxLength={64}
                  disabled={disabled}
                  onChange={(event) => edit(index, { name: event.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor={`${rowId}-provider`}>{t("councilMemberProvider")}</Label>
                <Input
                  id={`${rowId}-provider`}
                  value={member.provider}
                  minLength={1}
                  maxLength={64}
                  disabled={disabled}
                  onChange={(event) => edit(index, { provider: event.target.value })}
                />
              </div>
            </div>
            <div role="group" aria-labelledby={`${rowId}-model-label`} className="space-y-1.5">
              <p id={`${rowId}-model-label`} className="text-sm font-medium">
                {t("councilMemberModel")}
              </p>
              <ModelProfilePicker
                profiles={profiles}
                profilesStatus={profilesStatus}
                value={member.model_profile_id || null}
                disabled={disabled}
                onChange={(profileId) => {
                  const profile = profiles.find((candidate) => candidate.id === profileId);
                  edit(index, {
                    model_profile_id: profileId ?? "",
                    ...(profile ? { provider: profile.provider } : {}),
                  });
                }}
              />
            </div>
          </fieldset>
        );
      })}
    </div>
  );
}
