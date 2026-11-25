"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { MessageSquare, BellRing } from "lucide-react";
import { toast } from "sonner";
import { usePermissions } from "@/hooks/use-permissions";
import { useConsoleExperience } from "@/hooks/use-console-experience";
import { useOrgStore } from "@/stores";
import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type { ChatHomeOverrides, OnboardingReminderOverrides } from "@/lib/console-experience-api";
import { Perm } from "@/types/permissions";
import type { Organization } from "@/types/organization";
import { ErrorState } from "@/components/states";
import { ServiceCard } from "@/components/settings/service-card";
import { OnboardingReminderControls } from "@/components/settings/onboarding-reminder-controls";
import { ChatHomeControls } from "@/components/settings/chat-home-controls";

type OrganizationExperience = Pick<
  Organization,
  "id" | "chat_home_defaults" | "onboarding_reminders"
>;

export function OrgChatHomeSettings({ org }: { org: OrganizationExperience }) {
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { can } = usePermissions();
  if (activeOrgId !== org.id || !can(Perm.orgSettings)) return null;
  return <OrganizationChatHome org={org} />;
}
function OrganizationChatHome({ org }: { org: OrganizationExperience }) {
  const t = useTranslations("consoleExperience");
  const errors = useTranslations("errors");
  const client = useQueryClient();
  const experience = useConsoleExperience();
  const { data } = experience;
  const save = useMutation({
    mutationFn: (changes: {
      chat_home_defaults?: ChatHomeOverrides;
      onboarding_reminders?: OnboardingReminderOverrides;
    }) => {
      if (useOrgStore.getState().activeOrgId !== org.id) throw new Error(errors("sessionExpired"));
      return apiClient.patch<Organization>(`/orgs/${org.id}`, changes, {
        headers: { "X-Organization-Id": org.id },
      });
    },
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: qk.organizations.list() }),
        client.invalidateQueries({ queryKey: qk.consoleExperience.all() }),
      ]);
    },
    onError: (error) => toast.error(getErrorMessage(error, errors)),
  });
  return (
    <>
      <ServiceCard
        icon={MessageSquare}
        action={null}
        title={t("title")}
        description={t("organizationHint")}
      >
        {experience.error && (
          <ErrorState cta={{ label: t("retry"), onClick: () => void experience.refetch() }} />
        )}
        <ChatHomeControls
          mode="inheritance"
          value={org.chat_home_defaults}
          availability={data?.availability}
          disabled={save.isPending || !data}
          onChange={(field, value) => save.mutate({ chat_home_defaults: { [field]: value } })}
        />
      </ServiceCard>
      <ServiceCard
        icon={BellRing}
        action={null}
        title={t("remindersTitle")}
        description={t("remindersOrganizationHint")}
      >
        <OnboardingReminderControls
          value={org.onboarding_reminders}
          available={data?.reminders.availability}
          disabled={save.isPending || !data}
          onChange={(onboarding_reminders) => save.mutate({ onboarding_reminders })}
        />
      </ServiceCard>
    </>
  );
}
